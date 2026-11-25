"""Synthetic (fake) data for all three modules. No real people, firms, PANs or GSTINs.

Everything is generated from a fixed random seed, so the same seed always gives
exactly the same files. That makes the tests repeatable: we know in advance how
many problems were planted, so we can check the matching engine finds all of them.

What gets generated:
  * GST: 30 suppliers, 200 purchase-register invoices, and a GSTR-2B file with
    deliberate problems (see `PLANTED`), plus an answer key that is kept OUT of
    the uploaded files.
  * ITR: 3 salaried clients with different profiles.
  * MF: a 2016-2026 transaction history (SIPs, lump sums, partial redemptions)
    across equity, debt and "other" funds, plus 31 Jan 2018 NAVs for grandfathering.

Run `python -m taxdesk.sample_data --out sample_files` to write the files to disk.
"""

from __future__ import annotations

import argparse
import math
import random
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

from taxdesk.ids import make_fake_isin, make_gstin, make_pan
from taxdesk.rules import get_rule

DEFAULT_SEED: int = 2627

PURCHASE_COLUMNS: list[str] = [
    "Supplier GSTIN", "Supplier Name", "Invoice No", "Invoice Date",
    "Taxable Value", "IGST", "CGST", "SGST", "Total",
]
GSTR2B_COLUMNS: list[str] = [
    "Supplier GSTIN", "Trade/Legal Name", "Invoice No", "Invoice Date", "Invoice Value",
    "Taxable Value", "IGST", "CGST", "SGST", "ITC Availability",
]
MF_COLUMNS: list[str] = ["Date", "Scheme", "ISIN", "Fund Type", "Type", "Units", "NAV", "Amount"]

# Category keys shared with the GST matching engine (Stage 1).
MATCHED = "matched"
AMOUNT_DIFFERENCE = "amount_difference"
PROBABLE_MATCH = "probable_match"
IN_BOOKS_NOT_IN_2B = "in_books_not_in_2b"
IN_2B_NOT_IN_BOOKS = "in_2b_not_in_books"

N_SUPPLIERS = 30
N_INVOICES = 200
PLANTED: dict[str, int] = {
    IN_BOOKS_NOT_IN_2B: 10,   # we booked it, supplier never uploaded it -> ITC at risk
    IN_2B_NOT_IN_BOOKS: 6,    # supplier uploaded it, we never booked it
    AMOUNT_DIFFERENCE: 8,     # same invoice, different tax amount
    PROBABLE_MATCH: 5,        # same invoice, invoice number typed slightly differently
}
N_FORMAT_VARIANTS = 20        # same number written differently (case, separators, zero padding)
N_ROUNDING = 15               # 2B tax rounded to the rupee; difference < Rs 1, still "Matched"

GST_PERIOD_START = date(2026, 4, 1)
GST_PERIOD_END = date(2026, 9, 30)

_FIRST_WORDS = [
    "Sahyadri", "Indrayani", "Deccan", "Konkan", "Godavari", "Pavana", "Bhima", "Shivalik",
    "Narmada", "Kaveri", "Tapi", "Vindhya", "Aravali", "Malwa", "Sangam", "Nilgiri", "Purna",
    "Warna", "Satpura", "Ajinkya", "Chakan", "Talegaon", "Bhosari", "Mulshi", "Khadki",
    "Rajgad", "Torna", "Lohgad", "Sinhgad", "Purandar", "Velhe", "Panshet",
]
_SECOND_WORDS = [
    "Packaging", "Steel", "Polymers", "Fasteners", "Logistics", "Electricals", "Castings",
    "Tooling", "Chemicals", "Rubber", "Engineering", "Stationery", "Hydraulics", "Forgings",
    "Paints", "Bearings", "Wires", "Precision", "Infotech", "Transport",
]
# holder type -> (short suffix in our books, legal suffix in GSTR-2B)
_ENTITY_SUFFIX = {"C": ("Pvt Ltd", "PRIVATE LIMITED"), "F": ("LLP", "LLP"), "P": ("Enterprises", "ENTERPRISES")}
_OTHER_STATES = [29, 24, 33, 7, 9, 6, 36, 19]   # Karnataka, Gujarat, TN, Delhi, UP, Haryana, Telangana, WB
_INVOICE_STYLES = ["{p}/2026-27/{n:05d}", "{p}-{n:05d}/2026-27", "TI/{p}/{n:05d}/26-27"]


# =============================================================== helpers ==========

def _round_half_up(value: float, ndigits: int = 0) -> float:
    """Round like a human (0.5 always goes up), unlike Python's round(), which rounds 0.5 to even."""
    quantum = Decimal(1).scaleb(-ndigits)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _random_date(rng: random.Random, start: date, end: date) -> date:
    """A random date between start and end, both inclusive."""
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _split_tax(taxable: float, rate_pct: int, intra_state: bool) -> tuple[float, float, float]:
    """Return (IGST, CGST, SGST). Same-state supply: CGST + SGST, half each. Other state: IGST."""
    if intra_state:
        half = round(taxable * rate_pct / 200, 2)
        return 0.0, half, half
    return round(taxable * rate_pct / 100, 2), 0.0, 0.0


def _alnum(text: str) -> str:
    """Uppercase and keep only letters and digits (for quick similarity checks)."""
    return re.sub(r"[^0-9A-Z]", "", text.upper())


# =============================================================== GST ==============

@dataclass
class Supplier:
    """One fake supplier."""

    name: str
    legal_name: str
    gstin: str
    state_code: int
    prefix: str
    invoice_style: str


@dataclass
class GstSample:
    """Everything the GST module needs for a demo, plus the answer key for tests."""

    client_name: str
    client_gstin: str
    suppliers: pd.DataFrame
    purchase_register: pd.DataFrame
    gstr2b: pd.DataFrame
    answer_key: pd.DataFrame          # one row per invoice: what category it SHOULD land in
    expected_counts: dict[str, int]


def _make_suppliers(rng: random.Random, home_state: int) -> list[Supplier]:
    """Create 30 suppliers: about 60% in the client's state, the rest spread across other states."""
    firsts = rng.sample(_FIRST_WORDS, N_SUPPLIERS)
    seconds = [rng.choice(_SECOND_WORDS) for _ in range(N_SUPPLIERS)]
    suppliers: list[Supplier] = []
    used_prefixes: set[str] = set()
    for i, (first, second) in enumerate(zip(firsts, seconds)):
        holder = rng.choices(["C", "F", "P"], weights=[6, 2, 2])[0]
        short_sfx, legal_sfx = _ENTITY_SUFFIX[holder]
        name = f"{first} {second} {short_sfx}"
        legal = f"{first} {second} {legal_sfx}".upper()
        state = home_state if i < 18 else rng.choice(_OTHER_STATES)
        pan = make_pan(rng, holder, first[0])
        prefix = (first[:2] + second[0]).upper()
        while prefix in used_prefixes:
            prefix = (first[:2] + rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ")).upper()
        used_prefixes.add(prefix)
        suppliers.append(Supplier(name, legal, make_gstin(state, pan), state, prefix,
                                  rng.choice(_INVOICE_STYLES)))
    return suppliers


def _make_invoice_amount(rng: random.Random) -> tuple[float, int]:
    """A realistic taxable value (Rs 5,000 to Rs 6 lakh, with paise) and a GST rate."""
    taxable = math.exp(rng.gauss(10.3, 0.9))
    taxable = round(min(max(taxable, 5000), 600000) + rng.randint(1, 99) / 100, 2)
    rate = rng.choices([5, 18, 40], weights=[30, 67, 3])[0]
    return taxable, rate


def _format_variant(rng: random.Random, number: str) -> str:
    """Write the same invoice number differently (what portals and accountants actually do)."""
    tricks = [
        lambda s: s.lower(),
        lambda s: s.replace("/", "-"),
        lambda s: re.sub(r"(?<![0-9])0+(?=[0-9])", "", s),   # drop zero padding: 00142 -> 142
        lambda s: s.replace("/", " / "),
    ]
    return rng.choice(tricks)(number)


def _typo_seq(rng: random.Random, seq: int, taken: set[int]) -> tuple[int | None, str]:
    """Return (new_seq, kind) for a one-character typo in the running number, or (None, 'suffix')."""
    digits = f"{seq:03d}"
    options: list[tuple[int, str]] = []
    if digits[1] != digits[2]:
        options.append((int(digits[0] + digits[2] + digits[1]), "swapped digits"))
    for d in "0123456789":
        if d != digits[2]:
            options.append((int(digits[:2] + d), "one digit wrong"))
    options = [o for o in options if o[0] not in taken and o[0] >= 100]
    if not options or rng.random() < 0.25:
        return None, "extra character"
    return rng.choice(options)


def generate_gst_sample(seed: int = DEFAULT_SEED) -> GstSample:
    """Build the purchase register, the matching GSTR-2B and an answer key.

    Problems are planted on purpose (counts in PLANTED). Suppliers are split into
    separate groups for "missing from 2B", "typo" and "missing from books", so that
    each fuzzy candidate pair is unambiguous and the expected counts are exact.
    """
    rng = random.Random(seed)
    home_state = int(get_rule("gst.home_state_code"))
    client_pan = make_pan(rng, "C", "S")
    client_gstin = make_gstin(home_state, client_pan)
    client_name = "Shivneri Auto Components Pvt Ltd"

    suppliers = _make_suppliers(rng, home_state)

    # --- 1. Purchase register (our books) --------------------------------------
    weights = [rng.uniform(0.5, 3.0) for _ in suppliers]
    owner_idx = rng.choices(range(N_SUPPLIERS), weights=weights, k=N_INVOICES)
    for i in range(N_SUPPLIERS):          # every supplier gets at least one invoice
        if i not in owner_idx:
            owner_idx[rng.randrange(N_INVOICES)] = i

    books: list[dict] = []
    seqs_used: dict[int, set[int]] = {i: set() for i in range(N_SUPPLIERS)}
    for s_idx in range(N_SUPPLIERS):
        count = owner_idx.count(s_idx)
        dates = sorted(_random_date(rng, GST_PERIOD_START, GST_PERIOD_END) for _ in range(count))
        seq = rng.randint(100, 400)
        sup = suppliers[s_idx]
        for inv_date in dates:
            seq += rng.randint(1, 9)                         # other customers' invoices in between
            seqs_used[s_idx].add(seq)
            taxable, rate = _make_invoice_amount(rng)
            igst, cgst, sgst = _split_tax(taxable, rate, sup.state_code == home_state)
            books.append({
                "_supplier": s_idx, "_seq": seq, "_rate": rate,
                "Supplier GSTIN": sup.gstin, "Supplier Name": sup.name,
                "Invoice No": sup.invoice_style.format(p=sup.prefix, n=seq),
                "Invoice Date": inv_date, "Taxable Value": taxable,
                "IGST": igst, "CGST": cgst, "SGST": sgst,
                "Total": round(taxable + igst + cgst + sgst, 2),
            })

    # --- 2. Decide which invoices get which problem --------------------------
    supplier_order = list(range(N_SUPPLIERS))
    rng.shuffle(supplier_order)
    invoices_per_supplier = {i: owner_idx.count(i) for i in range(N_SUPPLIERS)}
    missing_suppliers: set[int] = set()
    cursor = 0
    while (len(missing_suppliers) < 3
           or sum(invoices_per_supplier[s] for s in missing_suppliers) < PLANTED[IN_BOOKS_NOT_IN_2B]):
        missing_suppliers.add(supplier_order[cursor])
        cursor += 1
    typo_suppliers = supplier_order[cursor:cursor + PLANTED[PROBABLE_MATCH]]
    cursor += PLANTED[PROBABLE_MATCH]
    extra_suppliers = supplier_order[cursor:cursor + PLANTED[IN_2B_NOT_IN_BOOKS]]

    all_rows = list(range(len(books)))
    # Take missing invoices round-robin across the group, so several suppliers are affected.
    queues = [rng.sample(rows, len(rows)) for rows in
              ([r for r in all_rows if books[r]["_supplier"] == s] for s in sorted(missing_suppliers))]
    missing_rows: list[int] = []
    while len(missing_rows) < PLANTED[IN_BOOKS_NOT_IN_2B]:
        for queue in queues:
            if queue and len(missing_rows) < PLANTED[IN_BOOKS_NOT_IN_2B]:
                missing_rows.append(queue.pop())
    typo_rows = [rng.choice([r for r in all_rows if books[r]["_supplier"] == s]) for s in typo_suppliers]
    taken = set(missing_rows) | set(typo_rows)
    free = [r for r in all_rows if r not in taken]
    rng.shuffle(free)
    amount_rows = free[:PLANTED[AMOUNT_DIFFERENCE]]
    variant_rows = free[len(amount_rows):len(amount_rows) + N_FORMAT_VARIANTS]
    rounding_pool = [r for r in free[len(amount_rows) + N_FORMAT_VARIANTS:]
                     if any(books[r][h] != int(books[r][h]) for h in ("IGST", "CGST", "SGST"))]
    rounding_rows = rounding_pool[:N_ROUNDING]

    # --- 3. Build GSTR-2B from the books, applying the problems ---------------
    gstr2b: list[dict] = []
    key: list[dict] = []
    for r, row in enumerate(books):
        sup = suppliers[row["_supplier"]]
        if r in missing_rows:
            key.append(_key(row["Supplier GSTIN"], row["Invoice No"], None, IN_BOOKS_NOT_IN_2B,
                            "supplier has not uploaded this invoice"))
            continue
        number = row["Invoice No"]
        taxable = row["Taxable Value"]
        igst, cgst, sgst = row["IGST"], row["CGST"], row["SGST"]
        category, note = MATCHED, ""
        if r in typo_rows:
            new_seq, kind = _typo_seq(rng, row["_seq"], seqs_used[row["_supplier"]])
            number = number + "A" if new_seq is None else sup.invoice_style.format(p=sup.prefix, n=new_seq)
            category, note = PROBABLE_MATCH, f"invoice number typo ({kind})"
        elif r in amount_rows:
            change = rng.choice([-1, 1]) * rng.uniform(0.05, 0.25)
            taxable = round(taxable * (1 + change), 2)
            igst, cgst, sgst = _split_tax(taxable, row["_rate"], sup.state_code == home_state)
            category, note = AMOUNT_DIFFERENCE, f"supplier reported taxable value {change:+.0%} different"
        elif r in variant_rows:
            number = _format_variant(rng, number)
            note = "same number, different format"
        elif r in rounding_rows:
            igst, cgst, sgst = (_round_half_up(v) for v in (igst, cgst, sgst))
            note = "tax rounded to the rupee (within tolerance)"
        gstr2b.append(_gstr2b_row(sup, number, row["Invoice Date"], taxable, igst, cgst, sgst))
        key.append(_key(row["Supplier GSTIN"], row["Invoice No"], number, category, note))

    for s_idx in extra_suppliers:                       # in 2B only: never booked by us
        sup = suppliers[s_idx]
        seq = max(seqs_used[s_idx]) + rng.randint(11, 40)
        seqs_used[s_idx].add(seq)
        taxable, rate = _make_invoice_amount(rng)
        igst, cgst, sgst = _split_tax(taxable, rate, sup.state_code == home_state)
        number = sup.invoice_style.format(p=sup.prefix, n=seq)
        gstr2b.append(_gstr2b_row(sup, number, _random_date(rng, GST_PERIOD_START, GST_PERIOD_END),
                                  taxable, igst, cgst, sgst))
        key.append(_key(sup.gstin, None, number, IN_2B_NOT_IN_BOOKS, "not recorded in our books"))

    rng.shuffle(gstr2b)                                 # the portal's order is not our order

    purchase_df = pd.DataFrame(books)[PURCHASE_COLUMNS]
    purchase_df["Invoice Date"] = pd.to_datetime(purchase_df["Invoice Date"])
    gstr2b_df = pd.DataFrame(gstr2b)[GSTR2B_COLUMNS]
    key_df = pd.DataFrame(key)
    expected = key_df["expected_category"].value_counts().to_dict()
    expected = {k: int(expected.get(k, 0)) for k in
                (MATCHED, AMOUNT_DIFFERENCE, PROBABLE_MATCH, IN_BOOKS_NOT_IN_2B, IN_2B_NOT_IN_BOOKS)}
    suppliers_df = pd.DataFrame([{
        "Supplier GSTIN": s.gstin, "Supplier Name": s.name, "Legal Name": s.legal_name,
        "State Code": f"{s.state_code:02d}",
    } for s in suppliers])

    return GstSample(client_name, client_gstin, suppliers_df, purchase_df, gstr2b_df, key_df, expected)


def _gstr2b_row(sup: Supplier, number: str, inv_date: date, taxable: float,
                igst: float, cgst: float, sgst: float) -> dict:
    """One GSTR-2B B2B row. Dates are text in DD-MM-YYYY, the way the portal exports them."""
    return {
        "Supplier GSTIN": sup.gstin, "Trade/Legal Name": sup.legal_name, "Invoice No": number,
        "Invoice Date": inv_date.strftime("%d-%m-%Y"),
        "Invoice Value": round(taxable + igst + cgst + sgst, 2), "Taxable Value": taxable,
        "IGST": igst, "CGST": cgst, "SGST": sgst, "ITC Availability": "Yes",
    }


def _key(gstin: str, books_no: str | None, gstr2b_no: str | None, category: str, note: str) -> dict:
    """One answer-key row (used by tests, never shown as part of an upload)."""
    return {"Supplier GSTIN": gstin, "Books Invoice No": books_no, "2B Invoice No": gstr2b_no,
            "expected_category": category, "note": note}


# =============================================================== ITR ==============

def generate_itr_clients(seed: int = DEFAULT_SEED) -> pd.DataFrame:
    """Three fictional salaried clients chosen to show different outcomes.

    C001: just above Rs 12.75 lakh salary -> new regime with marginal relief.
    C002: big deductions (rent, home loan, 80C, 80D) -> old regime may win.
    C003: salary plus let-out flat rent and FD interest -> mixed income.
    Amounts are in rupees per year. Figures are illustrative, not from any real person.
    """
    rng = random.Random(seed + 1)
    base = [
        {"client_id": "C001", "name": "Neha Kulkarni", "age": 29, "gross_salary": 1275000,
         "savings_interest": 8000, "fd_interest": 0, "rent_received": 0, "municipal_tax_paid": 0,
         "sec_123_80c": 50000, "sec_126_80d": 0, "home_loan_interest": 0, "hra_exemption": 0},
        {"client_id": "C002", "name": "Arjun Patil", "age": 38, "gross_salary": 1500000,
         "savings_interest": 12000, "fd_interest": 40000, "rent_received": 0, "municipal_tax_paid": 0,
         "sec_123_80c": 150000, "sec_126_80d": 25000, "home_loan_interest": 200000,
         "hra_exemption": 300000},
        {"client_id": "C003", "name": "Farah Shaikh", "age": 45, "gross_salary": 960000,
         "savings_interest": 6000, "fd_interest": 25000, "rent_received": 240000,
         "municipal_tax_paid": 12000, "sec_123_80c": 100000, "sec_126_80d": 15000,
         "home_loan_interest": 0, "hra_exemption": 0},
    ]
    for client in base:
        surname_initial = client["name"].split()[-1][0]
        client["pan"] = make_pan(rng, "P", surname_initial)
    cols = ["client_id", "name", "pan", "age", "gross_salary", "savings_interest", "fd_interest",
            "rent_received", "municipal_tax_paid", "sec_123_80c", "sec_126_80d",
            "home_loan_interest", "hra_exemption"]
    return pd.DataFrame(base)[cols]


# =============================================================== MF ===============

@dataclass
class MfSample:
    """A mutual fund transaction history plus 31 Jan 2018 NAVs for grandfathering."""

    transactions: pd.DataFrame
    fmv_31jan2018: dict[str, float]     # ISIN -> NAV on 31 Jan 2018 (equity schemes only)


_SCHEMES = [
    {"name": "Sahyadri Bluechip Equity Fund - Direct Growth", "fund_type": "equity",
     "start_nav": 24.0, "drift": 0.12, "vol": 0.15},
    {"name": "Konkan Midcap Opportunities Fund - Direct Growth", "fund_type": "equity",
     "start_nav": 38.0, "drift": 0.15, "vol": 0.20},
    {"name": "Indrayani Short Duration Debt Fund - Direct Growth", "fund_type": "debt",
     "start_nav": 1850.0, "drift": 0.068, "vol": 0.012},
    {"name": "Deccan Global Innovation Fund of Funds - Direct Growth", "fund_type": "other",
     "start_nav": 10.0, "drift": 0.10, "vol": 0.22},
]


def _monthly_navs(rng: random.Random, spec: dict) -> dict[tuple[int, int], float]:
    """Simulate a month-end NAV path from Jan 2016 to Dec 2026 (random walk with drift).

    Includes a March 2020 (COVID) crash and recovery so the history looks realistic.
    """
    navs: dict[tuple[int, int], float] = {}
    nav = spec["start_nav"]
    monthly_drift = (spec["drift"] - spec["vol"] ** 2 / 2) / 12
    monthly_vol = spec["vol"] / math.sqrt(12)
    for year in range(2016, 2027):
        for month in range(1, 13):
            shock = 0.0
            if (year, month) == (2020, 3):
                shock = -0.25 if spec["fund_type"] != "debt" else -0.01
            elif (year, month) in {(2020, 4), (2020, 5), (2020, 6)} and spec["fund_type"] != "debt":
                shock = 0.06
            nav *= math.exp(monthly_drift + monthly_vol * rng.gauss(0, 1) + shock)
            navs[(year, month)] = nav
    return navs


def _nav_on(navs: dict[tuple[int, int], float], day: date, drift: float) -> float:
    """NAV on a given day: that month's level, nudged a little for the day of the month."""
    return round(navs[(day.year, day.month)] * (1 + drift * (day.day - 1) / 365), 4)


def generate_mf_sample(seed: int = DEFAULT_SEED) -> MfSample:
    """Build a 2016-2026 MF history: SIPs, lump sums and partial redemptions in four schemes.

    Redemptions are given as a fraction of the units held on that day, so a sale can
    never exceed the holding. FY 2026-27 contains sales that exercise every rule:
    grandfathered equity lots, equity LTCG and STCG, pre- and post-April-2023 debt
    lots, and an "other" fund.
    """
    rng = random.Random(seed + 2)
    plan: dict[int, list[tuple[date, str, float]]] = {
        0: ([(date(y, m, 5), "buy", 5000 if y < 2021 else 8000)
             for y in range(2016, 2027) for m in range(1, 13) if (y, m) <= (2026, 10)]
            + [(date(2019, 6, 12), "sell", 0.10), (date(2023, 2, 20), "sell", 0.15),
               (date(2026, 8, 18), "sell", 0.30)]),
        1: [(date(2017, 3, 10), "buy", 100000), (date(2020, 4, 6), "buy", 50000),
            (date(2022, 11, 21), "sell", 0.40), (date(2024, 1, 15), "buy", 75000),
            (date(2025, 12, 1), "buy", 40000), (date(2026, 10, 7), "sell", 1.0)],
        2: [(date(2021, 6, 1), "buy", 200000), (date(2023, 5, 2), "buy", 150000),
            (date(2024, 9, 10), "buy", 50000), (date(2026, 9, 25), "sell", 0.70)],
        3: [(date(2022, 2, 14), "buy", 60000), (date(2023, 8, 16), "buy", 30000),
            (date(2026, 10, 20), "sell", 1.0)],
    }
    rows: list[dict] = []
    fmv: dict[str, float] = {}
    for s_idx, spec in enumerate(_SCHEMES):
        isin = make_fake_isin(rng)
        navs = _monthly_navs(rng, spec)
        if spec["fund_type"] == "equity":
            fmv[isin] = _nav_on(navs, date(2018, 1, 31), spec["drift"])
        held = 0.0
        for day, kind, value in sorted(plan[s_idx], key=lambda t: t[0]):
            nav = _nav_on(navs, day, spec["drift"])
            if kind == "buy":
                units = round(value / nav, 3)
                amount = float(value)
                held = round(held + units, 3)
            else:
                units = round(held * value, 3) if value < 1 else held
                amount = round(units * nav, 2)
                held = round(held - units, 3)
            rows.append({"Date": day, "Scheme": spec["name"], "ISIN": isin,
                         "Fund Type": spec["fund_type"], "Type": kind,
                         "Units": units, "NAV": nav, "Amount": amount})
    df = pd.DataFrame(rows, columns=MF_COLUMNS).sort_values(["Date", "Scheme"], kind="stable")
    df["Date"] = pd.to_datetime(df["Date"])
    return MfSample(df.reset_index(drop=True), fmv)


def mf_template() -> pd.DataFrame:
    """An empty transactions table with the expected column names, for the download button."""
    return pd.DataFrame(columns=MF_COLUMNS)


# =============================================================== files ============

def write_sample_files(out_dir: str | Path, seed: int = DEFAULT_SEED) -> list[Path]:
    """Write every sample file to `out_dir` (Excel for GST, CSV for the rest). Returns the paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gst = generate_gst_sample(seed)
    mf = generate_mf_sample(seed)
    written = {
        "gst_purchase_register.xlsx": lambda p: gst.purchase_register.to_excel(p, index=False),
        "gst_gstr2b.xlsx": lambda p: gst.gstr2b.to_excel(p, index=False, sheet_name="B2B"),
        "gst_answer_key.csv": lambda p: gst.answer_key.to_csv(p, index=False),
        "itr_clients.csv": lambda p: generate_itr_clients(seed).to_csv(p, index=False),
        "mf_transactions.csv": lambda p: mf.transactions.to_csv(p, index=False, date_format="%Y-%m-%d"),
        "mf_fmv_31jan2018.csv": lambda p: pd.DataFrame(
            list(mf.fmv_31jan2018.items()), columns=["ISIN", "NAV on 31-Jan-2018"]).to_csv(p, index=False),
        "mf_template.csv": lambda p: mf_template().to_csv(p, index=False),
    }
    paths = []
    for name, write in written.items():
        path = out / name
        write(path)
        paths.append(path)
    return paths


def main() -> None:
    """Command-line entry point: python -m taxdesk.sample_data --out sample_files"""
    parser = argparse.ArgumentParser(description="Write TaxDesk synthetic sample files.")
    parser.add_argument("--out", default="sample_files", help="output folder (default: sample_files)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed")
    args = parser.parse_args()
    for path in write_sample_files(args.out, args.seed):
        print(f"wrote {path}")
    counts = generate_gst_sample(args.seed).expected_counts
    print("planted GST categories:", counts)


if __name__ == "__main__":
    main()
