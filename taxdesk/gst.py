"""GST reconciliation: purchase register (our books) vs GSTR-2B (what suppliers uploaded).

Why this matters: a business can claim input tax credit (ITC) on a purchase only if
the supplier has reported that invoice, so that it shows up in the buyer's GSTR-2B.
If an invoice is in our books but not in 2B, the ITC on it is at risk.

Pipeline:
  1. guess_column_mapping()  map each file's headers to our standard fields
  2. clean_register()        validate GSTINs, parse amounts/dates, normalise invoice numbers
  3. reconcile()             exact match -> amount check -> fuzzy match -> leftovers
  4. summary / supplier table / follow-up email drafts

Everything here is pure Python and pandas, so it can be tested without a UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from taxdesk.formatting import format_inr
from taxdesk.ids import validate_gstin
from taxdesk.rules import get_rule
from taxdesk.sample_data import (AMOUNT_DIFFERENCE, IN_2B_NOT_IN_BOOKS, IN_BOOKS_NOT_IN_2B, MATCHED,
                                 PROBABLE_MATCH)
from taxdesk.tabular import _blank_mask, norm_header, parse_amounts, parse_dates, read_table

BOOKS = "books"
GSTR2B = "gstr2b"
TAX_HEADS = ("igst", "cgst", "sgst")

CATEGORY_ORDER: tuple[str, ...] = (MATCHED, AMOUNT_DIFFERENCE, PROBABLE_MATCH,
                                   IN_BOOKS_NOT_IN_2B, IN_2B_NOT_IN_BOOKS)
CATEGORY_LABELS: dict[str, str] = {
    MATCHED: "Matched",
    AMOUNT_DIFFERENCE: "Matched, amount difference",
    PROBABLE_MATCH: "Probable match, needs review",
    IN_BOOKS_NOT_IN_2B: "In books, not in 2B (ITC at risk)",
    IN_2B_NOT_IN_BOOKS: "In 2B, not in books",
}


# =============================================================== column mapping ===

@dataclass(frozen=True)
class FieldSpec:
    """One standard field we need from an uploaded file."""

    label: str
    synonyms: tuple[str, ...]
    required: bool = False


_COMMON: dict[str, FieldSpec] = {
    "gstin": FieldSpec("Supplier GSTIN", ("gstin", "supplier gstin", "gstin of supplier", "party gstin",
                                          "vendor gstin", "gstin uin", "gst no", "gst number"), True),
    "name": FieldSpec("Supplier Name", ("supplier name", "party name", "vendor name", "name",
                                        "trade legal name", "trade name", "legal name", "particulars")),
    "invoice_no": FieldSpec("Invoice No", ("invoice no", "invoice number", "inv no", "bill no",
                                           "bill number", "document number", "doc no",
                                           "supplier invoice no", "voucher ref no", "reference no"), True),
    "invoice_date": FieldSpec("Invoice Date", ("invoice date", "inv date", "bill date", "date",
                                               "document date", "doc date")),
    "taxable_value": FieldSpec("Taxable Value", ("taxable value", "taxable amount", "assessable value",
                                                 "taxable")),
    "igst": FieldSpec("IGST", ("igst", "integrated tax", "igst amount", "integrated tax amount")),
    "cgst": FieldSpec("CGST", ("cgst", "central tax", "cgst amount", "central tax amount")),
    "sgst": FieldSpec("SGST", ("sgst", "state ut tax", "sgst utgst", "state tax", "utgst",
                               "sgst amount", "state ut tax amount")),
}
FIELD_SPECS: dict[str, dict[str, FieldSpec]] = {
    BOOKS: {**_COMMON,
            "total": FieldSpec("Total", ("total", "invoice value", "total amount", "invoice amount",
                                         "gross amount", "bill amount"))},
    GSTR2B: {**_COMMON,
             "invoice_value": FieldSpec("Invoice Value", ("invoice value", "total invoice value",
                                                          "invoice amount", "total")),
             "itc_availability": FieldSpec("ITC Availability", ("itc availability", "itc available",
                                                                "itc eligibility", "eligible for itc"))},
}

_BOOKS_DETAIL = ["Books Invoice No", "Books Invoice Date", "Books Taxable Value",
                 "Books IGST", "Books CGST", "Books SGST", "Books Total Tax"]
_2B_DETAIL = ["2B Invoice No", "2B Invoice Date", "2B Taxable Value",
              "2B IGST", "2B CGST", "2B SGST", "2B Total Tax"]
_CATEGORY_COLUMNS: dict[str, list[str]] = {
    MATCHED: ["Books Invoice No", "2B Invoice No", "Books Invoice Date", "Books Taxable Value",
              "Books Total Tax", "2B Total Tax", "Tax Difference (2B - Books)", "ITC Availability",
              "Books Row", "2B Row"],
    AMOUNT_DIFFERENCE: ["Books Invoice No", "2B Invoice No", "Books Invoice Date", "Books Taxable Value",
                        "2B Taxable Value", "Books IGST", "2B IGST", "Books CGST", "2B CGST", "Books SGST",
                        "2B SGST", "Books Total Tax", "2B Total Tax", "Tax Difference (2B - Books)",
                        "ITC at Risk", "Note", "Books Row", "2B Row"],
    PROBABLE_MATCH: ["Books Invoice No", "2B Invoice No", "Similarity", "Books Invoice Date", "2B Invoice Date",
                     "Books Total Tax", "2B Total Tax", "Tax Difference (2B - Books)", "Note",
                     "Books Row", "2B Row"],
    IN_BOOKS_NOT_IN_2B: [*_BOOKS_DETAIL, "ITC at Risk", "GSTIN Issue", "Note", "Books Row"],
    IN_2B_NOT_IN_BOOKS: [*_2B_DETAIL, "ITC Availability", "GSTIN Issue", "Note", "2B Row"],
}


def columns_for_category(key: str) -> list[str]:
    """The columns worth showing for one category (the full table has every column)."""
    return ["Supplier GSTIN", "Supplier Name", *_CATEGORY_COLUMNS[key]]


GUESS_THRESHOLD = 85


class MappingError(ValueError):
    """Raised when the column mapping is unusable. `problems` lists each issue in plain words."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def header_synonyms(kind: str) -> list[str]:
    """Every header text we recognise for a file kind (used to find the header row)."""
    return [s for spec in FIELD_SPECS[kind].values() for s in (spec.label, *spec.synonyms)]


def guess_column_mapping(columns: list[str], kind: str) -> dict[str, str | None]:
    """Guess which uploaded column holds each standard field.

    Every (field, column) pair is scored: 100 for an exact synonym, otherwise a fuzzy
    score. Then the best pairs are taken first, and each column is used at most once.
    The user confirms or changes the guess in the UI.
    """
    specs = FIELD_SPECS[kind]
    scored: list[tuple[float, str, str]] = []
    for fname, spec in specs.items():
        names = [norm_header(s) for s in (spec.label, *spec.synonyms)]
        for col in columns:
            h = norm_header(col)
            if not h:
                continue
            best = 100.0 if h in names else max(fuzz.token_sort_ratio(h, n) for n in names)
            scored.append((best, fname, col))
    scored.sort(key=lambda t: -t[0])
    mapping: dict[str, str | None] = {f: None for f in specs}
    used: set[str] = set()
    for score, fname, col in scored:
        if score < GUESS_THRESHOLD or mapping[fname] is not None or col in used:
            continue
        mapping[fname] = col
        used.add(col)
    return mapping


def validate_mapping(mapping: dict[str, str | None], kind: str, columns: list[str]) -> list[str]:
    """Return a list of problems with a mapping (empty list = OK)."""
    specs = FIELD_SPECS[kind]
    problems = [f"Choose the column for '{spec.label}'."
                for fname, spec in specs.items() if spec.required and not mapping.get(fname)]
    if not any(mapping.get(h) for h in TAX_HEADS):
        problems.append("Choose at least one tax column (IGST, CGST or SGST).")
    chosen = [c for c in mapping.values() if c]
    missing = [c for c in chosen if c not in columns]
    if missing:
        problems.append(f"Column(s) not found in the file: {', '.join(missing)}.")
    dupes = sorted({c for c in chosen if chosen.count(c) > 1})
    if dupes:
        problems.append(f"The same column is chosen twice: {', '.join(dupes)}.")
    return problems


def read_register(source: Any, kind: str, filename: str | None = None,
                  sheet: str | int | None = None) -> pd.DataFrame:
    """Read an uploaded purchase register or GSTR-2B file (in memory), detecting the header row."""
    return read_table(source, filename=filename, sheet=sheet, expected_headers=header_synonyms(kind),
                      prefer_sheet_containing="b2b" if kind == GSTR2B else None)


# =============================================================== cleaning =========

_LEADING_ZEROS = re.compile(r"(?<![0-9])0+(?=[0-9])")
_SEPARATORS = re.compile(r"[\s/\-._]")


def invoice_text(value: object) -> str:
    """Invoice number as display text. Excel may store 142 as 142.0, so drop a trailing .0."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalise_invoice_no(value: object) -> str:
    """Make invoice numbers comparable: 'INV/0042-A' and 'inv 42a' both become 'INV42A'.

    Steps: uppercase; remove zero padding at the start of every run of digits
    (done BEFORE removing separators, so '2026-27/00142' keeps its boundary and
    becomes '2026-27/142'); then remove spaces and the characters / - . _
    """
    text = invoice_text(value).upper()
    text = _LEADING_ZEROS.sub("", text)
    return _SEPARATORS.sub("", text)


@dataclass
class CleanResult:
    """A cleaned register plus a list of problems found while cleaning (shown to the user)."""

    data: pd.DataFrame
    issues: pd.DataFrame
    rows_read: int
    rows_skipped: int


def clean_register(raw: pd.DataFrame, mapping: dict[str, str | None], kind: str) -> CleanResult:
    """Validate and standardise one uploaded file. Never raises on bad cells; flags them instead.

    Output columns: the standard fields plus inv_norm (normalised invoice number),
    total_tax, gstin_valid, gstin_issue, source_row (spreadsheet row) and occurrence
    (1st, 2nd... time the same GSTIN + invoice appears, so duplicates pair up 1-to-1).
    """
    problems = validate_mapping(mapping, kind, list(raw.columns))
    if problems:
        raise MappingError(problems)
    specs = FIELD_SPECS[kind]
    first_row = int(raw.attrs.get("first_data_row", 2))
    df = pd.DataFrame(index=raw.index)
    for fname in specs:
        col = mapping.get(fname)
        df[fname] = raw[col].astype(object) if col else None
    df["source_row"] = np.arange(len(raw)) + first_row
    issues: list[dict[str, Any]] = []

    def flag(rows: pd.Series, column: str, problem: str, values: pd.Series | None = None) -> None:
        for idx in rows[rows].index:
            issues.append({"Row": int(df.at[idx, "source_row"]), "Column": column, "Problem": problem,
                           "Value": "" if values is None else str(values.at[idx])})

    # 1. Blank rows and summary rows ("Total", "Grand Total") are skipped.
    mapped = [f for f in specs if mapping.get(f)]
    all_blank = pd.concat([_blank_mask(df[f]) for f in mapped], axis=1).all(axis=1)
    inv_blank = _blank_mask(df["invoice_no"])
    gstin_blank = _blank_mask(df["gstin"])
    label_text = (df["gstin"].astype(str) + " " + df["name"].astype(str)).str.lower()
    total_row = inv_blank & label_text.str.contains(r"\btotal\b", regex=True)
    no_invoice = inv_blank & ~all_blank & ~total_row
    flag(no_invoice, specs["invoice_no"].label, "No invoice number, row skipped")
    keep = ~(all_blank | total_row | no_invoice)
    rows_read = int((~all_blank).sum())
    df = df[keep].copy()

    # 2. Text fields.
    df["invoice_no"] = df["invoice_no"].map(invoice_text)
    df["inv_norm"] = df["invoice_no"].map(normalise_invoice_no)
    df["gstin"] = (df["gstin"].astype(object).where(~_blank_mask(df["gstin"]), "").astype(str)
                   .str.replace(r"\s+", "", regex=True).str.upper())
    df["name"] = df["name"].astype(object).where(~_blank_mask(df["name"]), "").astype(str).str.strip()

    # 3. GSTIN check (each distinct GSTIN validated once).
    checks = {g: validate_gstin(g) for g in df["gstin"].unique()}
    df["gstin_valid"] = df["gstin"].map(lambda g: checks[g].valid)
    df["gstin_issue"] = df["gstin"].map(lambda g: checks[g].reason)
    flag(~df["gstin_valid"], specs["gstin"].label, "Invalid GSTIN", df["gstin"] + ": " + df["gstin_issue"])

    # 4. Amounts.
    amount_fields = [f for f in ("taxable_value", *TAX_HEADS, "total", "invoice_value") if f in specs]
    for fname in amount_fields:
        values, bad = parse_amounts(df[fname])
        flag(bad, specs[fname].label, "Not a number, treated as 0", df[fname])
        df[fname] = values
    df["total_tax"] = df[list(TAX_HEADS)].sum(axis=1).round(2)
    total_field = "total" if kind == BOOKS else "invoice_value"
    if not mapping.get(total_field):
        df[total_field] = (df["taxable_value"] + df["total_tax"]).round(2)

    # 5. Dates.
    dates, bad = parse_dates(df["invoice_date"])
    flag(bad, specs["invoice_date"].label, "Date not recognised", df["invoice_date"])
    df["invoice_date"] = dates

    # 6. ITC availability (2B only). Unmapped = assume available.
    if kind == GSTR2B:
        itc = df["itc_availability"].astype(str).str.strip().str.lower()
        df["itc_availability"] = np.where(itc.isin(["no", "n", "ineligible", "not available"]), "No", "Yes")

    # 7. Duplicates: number each repeat of the same supplier + invoice.
    df["occurrence"] = df.groupby(["gstin", "inv_norm"]).cumcount()
    flag(df["occurrence"] > 0, specs["invoice_no"].label, "Duplicate invoice in this file", df["invoice_no"])

    issues_df = pd.DataFrame(issues, columns=["Row", "Column", "Problem", "Value"])
    if not issues_df.empty:
        issues_df = issues_df.sort_values("Row", kind="stable").reset_index(drop=True)
    return CleanResult(df.reset_index(drop=True), issues_df, rows_read, rows_read - len(df))


# =============================================================== matching =========

@dataclass
class ReconResult:
    """Everything the GST page needs to show and export."""

    lines: pd.DataFrame                       # one row per invoice (pair), with a category
    summary: dict[str, Any]
    supplier_table: pd.DataFrame
    books_issues: pd.DataFrame = field(default_factory=pd.DataFrame)
    gstr2b_issues: pd.DataFrame = field(default_factory=pd.DataFrame)
    settings: dict[str, float] = field(default_factory=dict)

    def category(self, key: str) -> pd.DataFrame:
        """Rows of one category, e.g. result.category('probable_match')."""
        return self.lines[self.lines["Category"] == key].reset_index(drop=True)


def _within_tolerance(b: pd.DataFrame | np.ndarray, g: pd.DataFrame | np.ndarray, tolerance: float) -> np.ndarray:
    """True where every tax head (IGST, CGST, SGST) differs by at most `tolerance` rupees."""
    diff = np.abs(np.asarray(b, dtype=float) - np.asarray(g, dtype=float))
    return np.all(np.round(diff, 2) <= tolerance, axis=-1)


def _fuzzy_pairs(left_b: pd.DataFrame, left_g: pd.DataFrame, tolerance: float,
                 threshold: float) -> list[tuple[int, int, float]]:
    """Pair leftover invoices of the SAME supplier whose numbers look alike and amounts agree.

    For each GSTIN, every leftover books invoice is scored against every leftover
    2B invoice (rapidfuzz cdist, fast C code). Candidates must score >= threshold AND
    be within tolerance on every tax head. Then best scores are taken first
    (ties broken by nearest invoice date), each invoice used at most once.
    """
    candidates: list[tuple[float, float, int, int]] = []
    g_groups = {k: v for k, v in left_g.groupby("gstin")}
    for gstin, sb in left_b.groupby("gstin"):
        sg = g_groups.get(gstin)
        if sg is None or not gstin:
            continue
        scores = process.cdist(sb["inv_norm"].tolist(), sg["inv_norm"].tolist(),
                               scorer=fuzz.ratio, score_cutoff=threshold)
        amounts_ok = _within_tolerance(sb[list(TAX_HEADS)].to_numpy()[:, None, :],
                                       sg[list(TAX_HEADS)].to_numpy()[None, :, :], tolerance)
        for i, j in np.argwhere((scores >= threshold) & amounts_ok):
            gap = abs((sb["invoice_date"].iat[i] - sg["invoice_date"].iat[j]).days) \
                if pd.notna(sb["invoice_date"].iat[i]) and pd.notna(sg["invoice_date"].iat[j]) else 9999
            candidates.append((-float(scores[i, j]), gap, int(sb["_bid"].iat[i]), int(sg["_gid"].iat[j])))
    candidates.sort()
    used_b: set[int] = set()
    used_g: set[int] = set()
    pairs: list[tuple[int, int, float]] = []
    for neg_score, _gap, bid, gid in candidates:
        if bid in used_b or gid in used_g:
            continue
        used_b.add(bid)
        used_g.add(gid)
        pairs.append((bid, gid, -neg_score))
    return pairs


_SIDE_COLS = {"gstin": "GSTIN", "name": "Name", "invoice_no": "Invoice No", "invoice_date": "Invoice Date",
              "taxable_value": "Taxable Value", "igst": "IGST", "cgst": "CGST", "sgst": "SGST",
              "total_tax": "Total Tax", "gstin_issue": "GSTIN Issue", "source_row": "Row"}


def _side(df: pd.DataFrame, prefix: str, id_col: str) -> pd.DataFrame:
    """Pick and rename one side's columns: 'igst' -> 'Books IGST' etc."""
    cols = {k: f"{prefix} {v}" for k, v in _SIDE_COLS.items()}
    extra = ["itc_availability"] if "itc_availability" in df.columns else []
    out = df[[id_col, *cols, *extra]].rename(columns=cols)
    return out.rename(columns={"itc_availability": "ITC Availability"})


def reconcile(books: CleanResult, gstr2b: CleanResult, tolerance: float | None = None,
              fuzzy_threshold: float | None = None) -> ReconResult:
    """Match a cleaned purchase register against a cleaned GSTR-2B.

    Order of matching:
      1. Exact: same GSTIN + same normalised invoice number (+ same occurrence for duplicates).
         Then compare IGST/CGST/SGST: all within tolerance -> Matched, else Amount difference.
      2. Fuzzy, on what is left: same GSTIN, invoice similarity >= threshold, amounts
         within tolerance -> Probable match (a human should confirm).
      3. Anything still unpaired is "In books, not in 2B" or "In 2B, not in books".
    """
    tolerance = float(get_rule("app_settings.gst_matching.amount_tolerance_rs")
                      if tolerance is None else tolerance)
    threshold = float(get_rule("app_settings.gst_matching.fuzzy_invoice_threshold")
                      if fuzzy_threshold is None else fuzzy_threshold)
    b = books.data.copy()
    g = gstr2b.data.copy()
    b["_bid"] = np.arange(len(b))
    g["_gid"] = np.arange(len(g))

    # Step 1: exact.
    keys = ["gstin", "inv_norm", "occurrence"]
    exact = b[keys + ["_bid", *TAX_HEADS]].merge(g[keys + ["_gid", *TAX_HEADS]], on=keys,
                                                 suffixes=("_b", "_g"))
    same_amount = _within_tolerance(exact[[f"{h}_b" for h in TAX_HEADS]],
                                    exact[[f"{h}_g" for h in TAX_HEADS]], tolerance)
    pairs = pd.DataFrame({"_bid": exact["_bid"], "_gid": exact["_gid"],
                          "Category": np.where(same_amount, MATCHED, AMOUNT_DIFFERENCE),
                          "Similarity": 100.0, "Match Method": "Exact"})

    # Step 2: fuzzy on the leftovers.
    left_b = b[~b["_bid"].isin(pairs["_bid"])]
    left_g = g[~g["_gid"].isin(pairs["_gid"])]
    fuzzy = _fuzzy_pairs(left_b, left_g, tolerance, threshold)
    if fuzzy:
        pairs = pd.concat([pairs, pd.DataFrame({
            "_bid": [p[0] for p in fuzzy], "_gid": [p[1] for p in fuzzy], "Category": PROBABLE_MATCH,
            "Similarity": [round(p[2], 1) for p in fuzzy], "Match Method": "Fuzzy"})], ignore_index=True)

    # Step 3: leftovers.
    only_b = b.loc[~b["_bid"].isin(pairs["_bid"]), ["_bid"]].assign(Category=IN_BOOKS_NOT_IN_2B)
    only_g = g.loc[~g["_gid"].isin(pairs["_gid"]), ["_gid"]].assign(Category=IN_2B_NOT_IN_BOOKS)
    allrows = pd.concat([pairs, only_b, only_g], ignore_index=True)

    lines = (allrows.merge(_side(b, "Books", "_bid"), on="_bid", how="left")
                    .merge(_side(g, "2B", "_gid"), on="_gid", how="left"))
    lines = _finish_lines(lines, b, g, tolerance)
    summary = _summary(lines, b, g)
    return ReconResult(lines, summary, supplier_summary(lines), books.issues, gstr2b.issues,
                       {"tolerance": tolerance, "fuzzy_threshold": threshold})


def _finish_lines(lines: pd.DataFrame, b: pd.DataFrame, g: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    """Add display columns: supplier, differences, ITC at risk, notes; order and sort the rows."""
    for prefix in ("Books", "2B"):
        for col in ("IGST", "CGST", "SGST", "Total Tax", "Taxable Value"):
            lines[f"{prefix} {col}"] = lines[f"{prefix} {col}"].astype(float)
    lines["Supplier GSTIN"] = lines["Books GSTIN"].fillna(lines["2B GSTIN"])
    books_name = lines["Books Name"].replace("", np.nan)
    lines["Supplier Name"] = books_name.fillna(lines["2B Name"]).fillna("")
    has_both = lines["Books Total Tax"].notna() & lines["2B Total Tax"].notna()
    lines["Tax Difference (2B - Books)"] = np.where(
        has_both, (lines["2B Total Tax"] - lines["Books Total Tax"]).round(2), np.nan)
    lines["ITC Availability"] = lines["ITC Availability"].fillna("")
    lines["GSTIN Issue"] = lines["Books GSTIN Issue"].fillna(lines["2B GSTIN Issue"]).fillna("")

    # ITC at risk: tax we booked that 2B does not support.
    cat = lines["Category"]
    books_tax = lines["Books Total Tax"].fillna(0.0)
    shortfall = (lines["Books Total Tax"] - lines["2B Total Tax"]).clip(lower=0).fillna(0.0)
    risk = np.select(
        [cat == IN_BOOKS_NOT_IN_2B,
         lines["ITC Availability"].eq("No") & cat.isin([MATCHED, AMOUNT_DIFFERENCE, PROBABLE_MATCH]),
         cat == AMOUNT_DIFFERENCE],
        [books_tax, books_tax, shortfall], default=0.0)
    lines["ITC at Risk"] = np.round(risk, 2)

    lines["Note"] = np.select(
        [cat == PROBABLE_MATCH, cat == AMOUNT_DIFFERENCE, cat == IN_BOOKS_NOT_IN_2B,
         cat == IN_2B_NOT_IN_BOOKS, lines["ITC Availability"].eq("No")],
        ["Invoice numbers differ slightly; confirm it is the same invoice",
         "Tax in 2B differs from books; ask supplier to amend or correct books",
         "Supplier has not reported this invoice; follow up before claiming ITC",
         "Not in books: missed entry, wrong GSTIN, or invoice not ours",
         "2B shows ITC not available"], default="")
    lines = _gstin_typo_hints(lines, tolerance)

    columns = ["Category", "Supplier GSTIN", "Supplier Name", "Books Invoice No", "2B Invoice No",
               "Books Invoice Date", "2B Invoice Date", "Books Taxable Value", "2B Taxable Value",
               "Books IGST", "Books CGST", "Books SGST", "Books Total Tax",
               "2B IGST", "2B CGST", "2B SGST", "2B Total Tax", "Tax Difference (2B - Books)",
               "ITC at Risk", "Match Method", "Similarity", "ITC Availability", "GSTIN Issue", "Note",
               "Books Row", "2B Row"]
    lines["Match Method"] = lines["Match Method"].fillna("")
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    lines = lines[columns].assign(_o=lines["Category"].map(order))
    return (lines.sort_values(["_o", "Supplier Name", "Books Invoice No", "2B Invoice No"], kind="stable")
                 .drop(columns="_o").reset_index(drop=True))


def _gstin_typo_hints(lines: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    """If an unmatched books invoice has the same number and tax as an unmatched 2B invoice under a
    DIFFERENT GSTIN, the GSTIN was probably keyed wrongly. Add a hint; the category stays the same."""
    ob = lines[lines["Category"] == IN_BOOKS_NOT_IN_2B]
    og = lines[lines["Category"] == IN_2B_NOT_IN_BOOKS]
    if ob.empty or og.empty:
        return lines
    left = pd.DataFrame({"i": ob.index, "k": ob["Books Invoice No"].map(normalise_invoice_no),
                         "gstin": ob["Supplier GSTIN"], "tax": ob["Books Total Tax"]})
    right = pd.DataFrame({"j": og.index, "k": og["2B Invoice No"].map(normalise_invoice_no),
                          "gstin": og["Supplier GSTIN"], "tax": og["2B Total Tax"]})
    m = left.merge(right, on="k", suffixes=("_b", "_g"))
    m = m[(m["gstin_b"] != m["gstin_g"]) & ((m["tax_b"] - m["tax_g"]).abs() <= tolerance)]
    for _, r in m.iterrows():
        lines.at[r["i"], "Note"] = f"Same invoice and tax found in 2B under GSTIN {r['gstin_g']}: check GSTIN"
        lines.at[r["j"], "Note"] = f"Same invoice and tax found in books under GSTIN {r['gstin_b']}: check GSTIN"
    return lines


def _summary(lines: pd.DataFrame, b: pd.DataFrame, g: pd.DataFrame) -> dict[str, Any]:
    """Headline numbers for the summary cards."""
    counts = lines["Category"].value_counts()
    itc_2b = g.loc[g.get("itc_availability", pd.Series("Yes", index=g.index)) != "No", "total_tax"].sum()
    only_2b = lines["Category"] == IN_2B_NOT_IN_BOOKS
    return {
        "itc_as_per_books": round(float(b["total_tax"].sum()), 2),
        "itc_as_per_2b": round(float(itc_2b), 2),
        "itc_at_risk": round(float(lines["ITC at Risk"].sum()), 2),
        "itc_in_2b_not_booked": round(float(lines.loc[only_2b, "2B Total Tax"].sum()), 2),
        "invoices_in_books": int(len(b)),
        "invoices_in_2b": int(len(g)),
        "counts": {k: int(counts.get(k, 0)) for k in CATEGORY_ORDER},
        "invalid_gstins": int(lines.loc[lines["GSTIN Issue"] != "", "Supplier GSTIN"].nunique()),
    }


def supplier_summary(lines: pd.DataFrame) -> pd.DataFrame:
    """One row per supplier: invoices, problems and ITC at risk, riskiest first."""
    cat = lines["Category"]
    t = lines.assign(
        _books=lines["Books Invoice No"].notna(),
        _missing=cat == IN_BOOKS_NOT_IN_2B, _diff=cat == AMOUNT_DIFFERENCE,
        _review=cat == PROBABLE_MATCH, _notbooks=cat == IN_2B_NOT_IN_BOOKS)
    out = t.groupby("Supplier GSTIN", sort=False).agg(**{
        "Supplier Name": ("Supplier Name", "first"),
        "Invoices in Books": ("_books", "sum"),
        "Missing from 2B": ("_missing", "sum"),
        "Amount Differences": ("_diff", "sum"),
        "Needs Review": ("_review", "sum"),
        "In 2B, Not in Books": ("_notbooks", "sum"),
        "ITC at Risk": ("ITC at Risk", "sum"),
    }).reset_index()
    out["ITC at Risk"] = out["ITC at Risk"].round(2)
    return out.sort_values(["ITC at Risk", "Missing from 2B", "Supplier Name"],
                           ascending=[False, False, True], kind="stable").reset_index(drop=True)


def run_reconciliation(books_raw: pd.DataFrame, gstr2b_raw: pd.DataFrame,
                       books_mapping: dict[str, str | None] | None = None,
                       gstr2b_mapping: dict[str, str | None] | None = None,
                       tolerance: float | None = None, fuzzy_threshold: float | None = None) -> ReconResult:
    """Convenience: guess mappings if not given, clean both files, reconcile."""
    books_mapping = books_mapping or guess_column_mapping(list(books_raw.columns), BOOKS)
    gstr2b_mapping = gstr2b_mapping or guess_column_mapping(list(gstr2b_raw.columns), GSTR2B)
    return reconcile(clean_register(books_raw, books_mapping, BOOKS),
                     clean_register(gstr2b_raw, gstr2b_mapping, GSTR2B), tolerance, fuzzy_threshold)


# =============================================================== emails ===========

def period_label(lines: pd.DataFrame) -> str:
    """'Apr 2026 to Sep 2026' from the books invoice dates (or '' if none)."""
    dates = pd.concat([lines["Books Invoice Date"], lines["2B Invoice Date"]]).dropna()
    if dates.empty:
        return ""
    start, end = dates.min().strftime("%b %Y"), dates.max().strftime("%b %Y")
    return start if start == end else f"{start} to {end}"


def draft_supplier_emails(result: ReconResult, client_name: str = "[Your company name]") -> list[dict[str, str]]:
    """Draft one follow-up email per supplier with missing or mismatched invoices.

    The text is only shown for copying. Nothing is ever sent from the app.
    """
    period = period_label(result.lines)
    issues = result.lines[result.lines["Category"].isin([IN_BOOKS_NOT_IN_2B, AMOUNT_DIFFERENCE])]
    drafts: list[dict[str, str]] = []
    order = result.supplier_table["Supplier GSTIN"].tolist()
    for gstin in [x for x in order if x in set(issues["Supplier GSTIN"])]:
        rows = issues[issues["Supplier GSTIN"] == gstin]
        name = rows["Supplier Name"].iat[0] or gstin
        missing = rows[rows["Category"] == IN_BOOKS_NOT_IN_2B]
        diffs = rows[rows["Category"] == AMOUNT_DIFFERENCE]
        lines = [f"Dear {name} team,", "",
                 f"While reconciling our purchase register with GSTR-2B{' for ' + period if period else ''}, "
                 f"we found the following differences for invoices issued by you (GSTIN {gstin}).", ""]
        if not missing.empty:
            lines.append("Invoices NOT reflecting in our GSTR-2B:")
            for k, (_, r) in enumerate(missing.iterrows(), 1):
                lines.append(f"  {k}. Invoice {r['Books Invoice No']} dated {_fmt_date(r['Books Invoice Date'])}, "
                             f"taxable value Rs {format_inr(r['Books Taxable Value'])}, "
                             f"GST Rs {format_inr(r['Books Total Tax'])}")
            lines.append("")
        if not diffs.empty:
            lines.append("Invoices reflecting with a DIFFERENT tax amount:")
            for k, (_, r) in enumerate(diffs.iterrows(), 1):
                lines.append(f"  {k}. Invoice {r['Books Invoice No']} dated {_fmt_date(r['Books Invoice Date'])}: "
                             f"GST as per our books Rs {format_inr(r['Books Total Tax'])}, "
                             f"as per GSTR-2B Rs {format_inr(r['2B Total Tax'])}")
            lines.append("")
        total = rows["ITC at Risk"].sum()
        lines += [f"Total GST credit affected: Rs {format_inr(total)}.", "",
                  "Could you please check these in your GSTR-1/IFF and upload or amend them at the earliest? "
                  "If they are already reported, kindly share the return period so we can verify.", "",
                  "Regards,", client_name]
        subject = f"GST reconciliation: invoices to check{' (' + period + ')' if period else ''}"
        drafts.append({"Supplier GSTIN": gstin, "Supplier Name": name, "Subject": subject,
                       "Body": "\n".join(lines), "ITC at Risk": round(float(total), 2)})
    return drafts


def _fmt_date(value: object) -> str:
    """dd-mm-yyyy for a timestamp, '' for missing."""
    return value.strftime("%d-%m-%Y") if isinstance(value, pd.Timestamp) and pd.notna(value) else "n/a"
