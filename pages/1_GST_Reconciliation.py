"""GST reconciliation page: results first; inputs (files, columns, settings) fold away once reconciled.

Layout only. All logic lives in taxdesk.gst and taxdesk.exports.
Uploaded files are read from memory (st.session_state for this browser session only)
and are never written to disk or shared between users.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from taxdesk.exports import dataframe_to_xlsx, gst_excel_report
from taxdesk.gst import (BOOKS, CATEGORY_LABELS, CATEGORY_ORDER, FIELD_SPECS, GSTR2B, MappingError,
                         clean_register, columns_for_category, draft_supplier_emails,
                         guess_column_mapping, period_label, read_register, reconcile, validate_mapping)
from taxdesk.rules import get_rule
from taxdesk.sample_data import (AMOUNT_DIFFERENCE, IN_2B_NOT_IN_BOOKS, IN_BOOKS_NOT_IN_2B, MATCHED,
                                 PROBABLE_MATCH, generate_gst_sample)
from taxdesk.tabular import TableReadError, excel_sheet_names
from ui_common import (Line, callout, footer, note_heading, note_total, page_header, rupees, setup_page, show_table,
                       signoff, statement, table_height)

setup_page("GST Reconciliation")
NOT_IN_FILE = "(not in file)"
FILE_LABELS = {BOOKS: "Purchase register", GSTR2B: "GSTR-2B (B2B)"}
SUBTITLE = "Purchase register vs GSTR-2B: ITC at risk and mismatches"


@st.cache_data(show_spinner=False)
def sample_data() -> tuple[pd.DataFrame, pd.DataFrame, str, bytes, bytes]:
    """Synthetic sample (safe to cache: contains no user data)."""
    s = generate_gst_sample()
    return (s.purchase_register, s.gstr2b, s.client_name,
            dataframe_to_xlsx(s.purchase_register, "Purchase Register"), dataframe_to_xlsx(s.gstr2b, "B2B"))


def load_upload(kind: str, container) -> tuple[pd.DataFrame | None, str]:
    """Upload widget + sheet picker. Returns (raw table or None, a signature of the file)."""
    file = container.file_uploader(FILE_LABELS[kind], type=["xlsx", "csv"], key=f"gst_upload_{kind}",
                                   help="Excel (.xlsx) or CSV. Read in memory only; never saved.")
    if file is None:
        return None, ""
    data = file.getvalue()
    sheet = None
    if file.name.lower().endswith((".xlsx", ".xlsm")):
        try:
            sheets = excel_sheet_names(data)
        except TableReadError as exc:
            container.error(str(exc))
            return None, ""
        if len(sheets) > 1:
            default = next((i for i, n in enumerate(sheets) if "b2b" in n.lower()), 0)
            sheet = container.selectbox("Sheet", sheets, index=default, key=f"gst_sheet_{kind}")
    signature = f"{file.name}|{len(data)}|{sheet}"
    cache = st.session_state.setdefault("gst_read_cache", {})        # this session only
    if cache.get(kind, ("",))[0] != signature:
        try:
            cache[kind] = (signature, read_register(data, kind, filename=file.name, sheet=sheet))
        except TableReadError as exc:
            container.error(str(exc))
            return None, ""
    raw = cache[kind][1]
    container.caption(f"{len(raw):,} rows read")
    return raw, signature


def mapping_editor(kind: str, raw: pd.DataFrame, signature: str) -> dict[str, str | None]:
    """Show the guessed column mapping and let the user change it."""
    columns = list(raw.columns)
    guess = guess_column_mapping(columns, kind)
    problems = validate_mapping(guess, kind, columns)
    if problems:
        st.warning("Some columns could not be matched. Choose them below.")
    else:
        st.caption("We matched every column. Change any that are wrong.")
    mapping: dict[str, str | None] = {}
    options = [NOT_IN_FILE, *columns]
    cols = st.columns(3)
    for i, (fname, spec) in enumerate(FIELD_SPECS[kind].items()):
        current = guess.get(fname)
        choice = cols[i % 3].selectbox(
            spec.label + (" *" if spec.required else ""), options,
            index=options.index(current) if current in options else 0,
            key=f"gst_map_{kind}_{signature}_{fname}")
        mapping[fname] = None if choice == NOT_IN_FILE else choice
    st.caption("\\* required. At least one of IGST / CGST / SGST is also required.")
    st.dataframe(raw.head(5), hide_index=True, width="stretch")
    return mapping


def supplier_status(row: pd.Series) -> str:
    """One status word per supplier, worst finding first."""
    if row["Missing from 2B"]:
        return "Not in 2B"
    if row["Amount Differences"]:
        return "Difference"
    if row["Needs Review"]:
        return "Needs review"
    if row["In 2B, Not in Books"]:
        return "Not in books"
    return "Agreed"


def paise(value: float) -> float:
    """Round to paise, the unit GST credit is tracked in."""
    return round(float(value), 2)


def itc_figures(result) -> dict[str, float | int]:
    """Statement figures in paise. Totals are derived from the rounded lines, so the statement adds up exactly."""
    s, lines = result.summary, result.lines
    risk = lines[lines["ITC at Risk"] > 0]
    by_cat = risk.groupby("Category")["ITC at Risk"].agg(["sum", "count"])

    def part(*keys: str) -> tuple[int, float]:
        rows = by_cat.loc[by_cat.index.intersection(list(keys))]
        return int(rows["count"].sum()), paise(rows["sum"].sum())

    f: dict[str, float | int] = {"books": paise(s["itc_as_per_books"]), "n_risk": len(risk),
                                 "n_suppliers": int(risk["Supplier GSTIN"].nunique())}
    (f["n_miss"], f["missing"]), (f["n_diff"], f["shortfall"]) = part(IN_BOOKS_NOT_IN_2B), part(AMOUNT_DIFFERENCE)
    f["n_other"], f["other"] = part(MATCHED, PROBABLE_MATCH)
    f["risk"] = paise(f["missing"] + f["shortfall"] + f["other"])
    f["after"] = paise(f["books"] - f["risk"])
    f["probable"] = paise(result.category(PROBABLE_MATCH)["Books Total Tax"].sum())
    f["not_booked"] = paise(s["itc_in_2b_not_booked"])
    f["in_2b"] = paise(s["itc_as_per_2b"])
    return f


def itc_statement(result, f: dict[str, float | int]) -> list[Line]:
    """Statement of ITC: books, less amounts at risk by cause, then memo lines. Notes 1-6 hold the detail."""
    s, counts = result.summary, result.summary["counts"]
    out = [
        Line("ITC as per purchase register", [s["invoices_in_books"], f["books"]], 1),
        Line("Less: not reflected in GSTR-2B", [f["n_miss"], f["missing"]], 2, "less"),
        Line("Less: shortfall on amount differences", [f["n_diff"], f["shortfall"]], 3, "less"),
    ]
    if f["other"]:
        out.append(Line("Less: ITC shown as not available in GSTR-2B", [f["n_other"], f["other"]], 6, "less"))
    out += [
        Line("ITC after amounts at risk", [None, f["after"]], None, "total"),
        Line("ITC at risk", [f["n_risk"], f["risk"]], "2–3", "risk"),
        Line("Probable matches to confirm", [counts[PROBABLE_MATCH], f["probable"]], 4, "memo"),
        Line("Credit in GSTR-2B not in books", [counts[IN_2B_NOT_IN_BOOKS], f["not_booked"]], 5, "memo"),
        Line("ITC as per GSTR-2B (available)", [s["invoices_in_2b"], f["in_2b"]], None, "memo"),
    ]
    return out


# Notes 2-6 in page order: (category key, title, the amount column that ties to the statement, total label).
# Note 1 is the supplier position, Note 7 the email drafts.
NOTES = [
    (IN_BOOKS_NOT_IN_2B, "Invoices in books, not in GSTR-2B", "ITC at Risk", "Total ITC not reflected in GSTR-2B"),
    (AMOUNT_DIFFERENCE, "Amount differences", "ITC at Risk", "Total shortfall on amount differences"),
    (PROBABLE_MATCH, "Probable matches to confirm", "Books Total Tax", "Total ITC on probable matches"),
    (IN_2B_NOT_IN_BOOKS, "In GSTR-2B, not in books", "2B Total Tax", "Total credit in GSTR-2B not in books"),
    (MATCHED, "Agreed invoices", "Books Total Tax", "Total ITC on agreed invoices"),
]
COLUMN_LABELS = {
    "Supplier Name": "Supplier", "Supplier GSTIN": "GSTIN", "Books Invoice No": "Invoice",
    "Books Invoice Date": "Date", "Books Taxable Value": "Taxable (₹)", "Books IGST": "IGST (₹)",
    "Books CGST": "CGST (₹)", "Books SGST": "SGST (₹)", "Books Total Tax": "ITC (₹)",
    "2B Invoice No": "Invoice in 2B", "2B Invoice Date": "Date in 2B", "2B Taxable Value": "Taxable in 2B (₹)",
    "2B IGST": "IGST in 2B (₹)", "2B CGST": "CGST in 2B (₹)", "2B SGST": "SGST in 2B (₹)",
    "2B Total Tax": "ITC in 2B (₹)", "Tax Difference (2B - Books)": "Difference (₹)",
    "ITC at Risk": "ITC at risk (₹)", "Books Row": "Row in books", "2B Row": "Row in 2B",
}
NOTE_WIDTHS = {"Supplier Name": 210, "Books Invoice No": 165, "2B Invoice No": 165, "Supplier GSTIN": 160}


def note_columns(key: str, tie: str) -> tuple[list[str], dict[str, str]]:
    """Column order and display labels for one note: supplier, invoice and the tying amount first."""
    invoice = "2B Invoice No" if key == IN_2B_NOT_IN_BOOKS else "Books Invoice No"
    lead = [invoice, tie, "Supplier Name", "Supplier GSTIN"]
    # for missing invoices the books tax IS the ITC at risk, so the second column would only repeat it
    skip = {"Books Total Tax"} if key == IN_BOOKS_NOT_IN_2B else set()
    order = lead + [c for c in columns_for_category(key) if c not in lead and c not in skip]
    labels = {c: COLUMN_LABELS.get(c, c) for c in order}
    if key == IN_2B_NOT_IN_BOOKS:          # one-sided table: the 2B columns need no "in 2B" suffix
        labels.update({c: COLUMN_LABELS.get("Books " + c[3:], c[3:]) for c in order if c.startswith("2B ")})
        labels["2B Row"] = "Row in 2B"
    return order, labels


def render_results(stored: dict, client: str) -> None:
    """Statement of ITC with callout and export, then the numbered notes and the approval block."""
    result, drafts = stored["result"], stored["drafts"]
    s, counts = result.summary, result.summary["counts"]
    f = itc_figures(result)
    left, right = st.columns([1.35, 1], gap="medium")
    with left:
        statement("Statement of input tax credit", ["Particulars", "Invoices", "Amount (₹)"],
                  itc_statement(result, f), decimals=2)
    with right:
        if f["risk"]:
            text = f"on {f['n_risk']} invoices from {f['n_suppliers']} suppliers. See Notes 2 and 3."
        else:
            text = "Every invoice in the books is supported by GSTR-2B."
        callout("ITC at risk this period", rupees(f["risk"], 2), text, "risk" if f["risk"] else "agreed",
                [("Agreed", counts[MATCHED], "agreed"), ("Amount differs", counts[AMOUNT_DIFFERENCE], "review"),
                 ("Probable", counts[PROBABLE_MATCH], "review"), ("Not in 2B", counts[IN_BOOKS_NOT_IN_2B], "risk"),
                 ("Not in books", counts[IN_2B_NOT_IN_BOOKS], "neutral")])
        a, b = st.columns(2)
        a.download_button("Download Excel", stored["excel"], f"gst_reconciliation_{date.today():%Y%m%d}.xlsx",
                          type="primary", width="stretch", icon=":material/download:",
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        b.markdown(f"<a class='td-jump' href='#note-7'>Supplier emails ({len(drafts)})</a>", unsafe_allow_html=True)

    n_issues = len(result.books_issues) + len(result.gstr2b_issues)
    if n_issues:
        with st.expander(f"{n_issues} data problem(s) found while reading the files", icon=":material/warning:"):
            issues = pd.concat([result.books_issues.assign(File=FILE_LABELS[BOOKS]),
                                result.gstr2b_issues.assign(File=FILE_LABELS[GSTR2B])], ignore_index=True)
            show_table(issues[["File", "Row", "Column", "Problem", "Value"]])

    search = st.text_input("Filter the notes by supplier name or GSTIN", placeholder="Type to filter every table")

    def filtered(df: pd.DataFrame) -> pd.DataFrame:
        if not search:
            return df
        mask = (df["Supplier Name"].str.contains(search, case=False, regex=False)
                | df["Supplier GSTIN"].str.contains(search, case=False, regex=False))
        return df[mask]

    suppliers = filtered(result.supplier_table.copy())
    suppliers.insert(0, "Status", [supplier_status(r) for _, r in suppliers.iterrows()])
    suppliers = suppliers[["Status", "ITC at Risk", "Supplier Name", "Supplier GSTIN", "Invoices in Books",
                           "Missing from 2B", "Amount Differences", "Needs Review", "In 2B, Not in Books"]]
    note_heading(1, "Supplier-wise position", f"{len(suppliers)} suppliers, riskiest first")
    show_table(suppliers, height=table_height(len(suppliers)), status_col="Status",
               labels={"Supplier Name": "Supplier", "ITC at Risk": "ITC at risk (₹)", "Supplier GSTIN": "GSTIN",
                       "Invoices in Books": "Invoices", "Missing from 2B": "Not in 2B",
                       "Amount Differences": "Differences", "Needs Review": "Review",
                       "In 2B, Not in Books": "Not in books"},
               widths={"Status": 95, "Supplier Name": 230, "Supplier GSTIN": 160})
    note_total([("Total ITC at risk" + (" (filtered)" if search else ""), paise(suppliers["ITC at Risk"].sum()))])
    for number, (key, title, tie, total_label) in enumerate(NOTES, start=2):
        order, labels = note_columns(key, tie)
        table = filtered(result.category(key)[order])
        zero = [c for c in table.columns if c != tie and pd.api.types.is_numeric_dtype(table[c])
                and not c.endswith("Row") and len(table) and (table[c].fillna(0) == 0).all()]
        table = table.drop(columns=zero)            # e.g. IGST on an all-intra-state note
        note_heading(number, title, f"{len(table)} invoice{'s' if len(table) != 1 else ''}")
        if table.empty:
            st.success("Nothing in this note.")
        else:
            show_table(table, height=table_height(len(table)), labels=labels,
                       widths={c: w for c, w in NOTE_WIDTHS.items() if c in table.columns})
            note_total([(total_label + (" (filtered)" if search else ""), paise(table[tie].sum()))])

    note_heading(7, "Supplier follow-up drafts", f"{len(drafts)} draft{'s' if len(drafts) != 1 else ''}")
    st.info("These are drafts only. Copy one and send it from your own email. "
            "TaxDesk never sends emails or files anything.")
    if drafts:
        labels = [f"{d['Supplier Name']}: {rupees(d['ITC at Risk'])} at risk" for d in drafts]
        pick = st.selectbox("Supplier", range(len(drafts)), format_func=lambda i: labels[i])
        st.markdown("**Subject**")
        st.code(drafts[pick]["Subject"], language=None, wrap_lines=True)
        st.markdown("**Body**")
        st.code(drafts[pick]["Body"], language=None, wrap_lines=True)
    signoff(client)


# ============================================================== page ============

header_slot = st.empty()        # filled last, so the header names the client and period
results_slot = st.container()   # results sit directly under the header

if st.session_state.pop("gst_load_sample", False):       # set by the Home page button
    st.session_state["gst_source"] = "Sample data"
st.session_state.setdefault("gst_source", "Upload files")
stored = st.session_state.get("gst_result")
inputs_label = (f"Inputs: {stored['label']}" if stored else "Load files, check columns and settings")

books_raw = twob_raw = None
books_sig = twob_sig = ""
client_name = ""
with st.expander(inputs_label, expanded=stored is None, icon=":material/tune:"):
    source = st.segmented_control("Data source", ["Upload files", "Sample data"], key="gst_source",
                                  label_visibility="collapsed")
    default_client = ""
    if source == "Sample data":
        books_raw, twob_raw, default_client, books_xlsx, twob_xlsx = sample_data()
        books_sig, twob_sig = "sample-books", "sample-2b"
        st.info("Synthetic data: 30 fake suppliers, 200 invoices. Planted problems: 10 missing from 2B, "
                "6 missing from books, 8 amount differences, 5 invoice-number typos.")
        c1, c2 = st.columns(2)
        c1.download_button("Download sample purchase register", books_xlsx, "sample_purchase_register.xlsx",
                           width="stretch", icon=":material/table_view:")
        c2.download_button("Download sample GSTR-2B", twob_xlsx, "sample_gstr2b.xlsx", width="stretch",
                           icon=":material/table_view:")
    elif source == "Upload files":
        c1, c2 = st.columns(2)
        books_raw, books_sig = load_upload(BOOKS, c1)
        twob_raw, twob_sig = load_upload(GSTR2B, c2)
    else:
        st.caption("Choose a data source above.")

    if books_raw is not None and twob_raw is not None:
        st.subheader("Columns")
        map_tabs = st.tabs([f"{FILE_LABELS[BOOKS]} columns", f"{FILE_LABELS[GSTR2B]} columns"])
        with map_tabs[0]:
            books_map = mapping_editor(BOOKS, books_raw, books_sig)
        with map_tabs[1]:
            twob_map = mapping_editor(GSTR2B, twob_raw, twob_sig)

        st.subheader("Settings")
        s1, s2, s3 = st.columns(3)
        tolerance = s1.number_input(
            "Amount tolerance (₹ per tax head)", min_value=0.0, max_value=1000.0, step=0.5,
            value=float(get_rule("app_settings.gst_matching.amount_tolerance_rs")),
            help="Differences up to this amount in IGST, CGST or SGST still count as matched.")
        threshold = s2.slider(
            "Fuzzy match threshold", min_value=70, max_value=100,
            value=int(get_rule("app_settings.gst_matching.fuzzy_invoice_threshold")),
            help="How similar two invoice numbers must be (0-100) to be suggested as a probable match.")
        client_name = s3.text_input("Your business name (for emails)", value=default_client,
                                    placeholder="e.g. ABC Traders")

        if st.button("Reconcile", type="primary", width="stretch", icon=":material/fact_check:"):
            try:
                with st.spinner("Matching invoices..."):
                    books = clean_register(books_raw, books_map, BOOKS)
                    twob = clean_register(twob_raw, twob_map, GSTR2B)
                    result = reconcile(books, twob, tolerance, threshold)
                    drafts = draft_supplier_emails(result, client_name or "[Your business name]")
                    st.session_state["gst_result"] = {
                        "result": result, "drafts": drafts, "inputs": (books_sig, twob_sig),
                        "client": client_name, "excel": gst_excel_report(result, client_name, drafts),
                        "label": f"{source.lower()} · tolerance ₹{tolerance:g} · threshold {threshold}"}
                st.rerun()                                    # redraw with results first, inputs folded
            except MappingError as exc:
                for problem in exc.problems:
                    st.error(problem)

# ============================================================== results =========

current = stored if stored and books_raw is not None and stored["inputs"] == (books_sig, twob_sig) else None
with results_slot:
    if current:
        render_results(current, current.get("client", ""))
    elif stored and books_raw is not None:
        st.info("The files changed. Press **Reconcile** to see results for the new files.")

page_header("GST reconciliation", SUBTITLE,
            period_label(current["result"].lines) if current else "Upload both files or use sample data",
            current.get("client", "") if current else "", target=header_slot)
footer()
