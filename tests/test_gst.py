"""Tests for the GST reconciliation engine."""

import io
import time

import pandas as pd
import pytest
from openpyxl import Workbook

from taxdesk.gst import (BOOKS, GSTR2B, MappingError, clean_register, draft_supplier_emails,
                         guess_column_mapping, normalise_invoice_no, parse_amounts, read_register,
                         reconcile, run_reconciliation)
from taxdesk.sample_data import (AMOUNT_DIFFERENCE, IN_2B_NOT_IN_BOOKS, IN_BOOKS_NOT_IN_2B, MATCHED,
                                 PLANTED, PROBABLE_MATCH, generate_gst_sample)


@pytest.fixture(scope="module")
def sample():
    return generate_gst_sample()


@pytest.fixture(scope="module")
def result(sample):
    return run_reconciliation(sample.purchase_register, sample.gstr2b)


# ------------------------------------------------------------- normalisation ----

def test_spec_example_invoices_match() -> None:
    assert normalise_invoice_no("INV/0042-A") == normalise_invoice_no("inv 42a") == "INV42A"


@pytest.mark.parametrize("a,b", [
    ("ABC/2026-27/00142", "abc-2026-27-142"),
    ("TI/XYZ/00007/26-27", "TI / XYZ / 7 / 26-27"),
    ("INV0042", "INV42"),
    ("142", 142.0),                          # Excel turned the number into a float
    ("A_1.05", "a-1-5"),
])
def test_normalisation_equivalents(a, b) -> None:
    assert normalise_invoice_no(a) == normalise_invoice_no(b)


def test_normalisation_keeps_real_differences() -> None:
    assert normalise_invoice_no("INV/100") != normalise_invoice_no("INV/10")
    assert normalise_invoice_no("INV-0") == "INV0"


# ------------------------------------------------------------- the planted data --

def test_synthetic_data_gives_exactly_the_planted_counts(result, sample) -> None:
    assert result.summary["counts"] == sample.expected_counts
    for category, n in PLANTED.items():
        assert result.summary["counts"][category] == n


def test_every_invoice_lands_in_its_expected_category(result, sample) -> None:
    """Row-by-row check against the answer key, not just the totals."""
    key = sample.answer_key
    books_side = key[key["Books Invoice No"].notna()]
    got = result.lines.dropna(subset=["Books Invoice No"]).set_index(
        ["Supplier GSTIN", "Books Invoice No"])["Category"]
    for _, row in books_side.iterrows():
        assert got.loc[(row["Supplier GSTIN"], row["Books Invoice No"])] == row["expected_category"]
    extra = result.category(IN_2B_NOT_IN_BOOKS)
    expected_extra = key[key["expected_category"] == IN_2B_NOT_IN_BOOKS]
    assert set(extra["2B Invoice No"]) == set(expected_extra["2B Invoice No"])


def test_itc_at_risk_adds_up(result) -> None:
    lines = result.lines
    missing = lines.loc[lines["Category"] == IN_BOOKS_NOT_IN_2B, "Books Total Tax"].sum()
    diffs = lines[lines["Category"] == AMOUNT_DIFFERENCE]
    shortfall = (diffs["Books Total Tax"] - diffs["2B Total Tax"]).clip(lower=0).sum()
    assert result.summary["itc_at_risk"] == pytest.approx(missing + shortfall, abs=0.01)
    assert result.supplier_table["ITC at Risk"].sum() == pytest.approx(result.summary["itc_at_risk"], abs=0.01)
    assert result.supplier_table["ITC at Risk"].is_monotonic_decreasing


def test_tolerance_is_configurable(sample) -> None:
    """With zero tolerance, the 15 'rounded to the rupee' invoices become amount differences."""
    strict = run_reconciliation(sample.purchase_register, sample.gstr2b, tolerance=0)
    assert strict.summary["counts"][AMOUNT_DIFFERENCE] == PLANTED[AMOUNT_DIFFERENCE] + 15
    assert strict.summary["counts"][MATCHED] == sample.expected_counts[MATCHED] - 15


def test_fuzzy_threshold_is_configurable(sample) -> None:
    """At 99 the typo pairs are no longer accepted, so each becomes one missing + one extra."""
    strict = run_reconciliation(sample.purchase_register, sample.gstr2b, fuzzy_threshold=99)
    c = strict.summary["counts"]
    assert c[PROBABLE_MATCH] == 0
    assert c[IN_BOOKS_NOT_IN_2B] == PLANTED[IN_BOOKS_NOT_IN_2B] + PLANTED[PROBABLE_MATCH]


def test_email_drafts(result) -> None:
    drafts = draft_supplier_emails(result, "Test Client")
    affected = result.lines[result.lines["Category"].isin([IN_BOOKS_NOT_IN_2B, AMOUNT_DIFFERENCE])]
    assert len(drafts) == affected["Supplier GSTIN"].nunique()
    for d in drafts:
        for inv in affected.loc[affected["Supplier GSTIN"] == d["Supplier GSTIN"], "Books Invoice No"]:
            assert inv in d["Body"]
        assert d["Body"].endswith("Test Client")


# ------------------------------------------------------------- column mapping ---

def test_guess_mapping_on_sample_headers(sample) -> None:
    m = guess_column_mapping(list(sample.purchase_register.columns), BOOKS)
    assert m["gstin"] == "Supplier GSTIN" and m["invoice_no"] == "Invoice No" and m["total"] == "Total"
    m2 = guess_column_mapping(list(sample.gstr2b.columns), GSTR2B)
    assert m2["name"] == "Trade/Legal Name" and m2["invoice_value"] == "Invoice Value"
    assert m2["itc_availability"] == "ITC Availability"


def test_guess_mapping_on_portal_style_headers() -> None:
    cols = ["GSTIN of supplier", "Trade/Legal name", "Invoice number", "Invoice type", "Invoice Date",
            "Invoice Value(₹)", "Place of supply", "Taxable Value (₹)", "Integrated Tax(₹)",
            "Central Tax(₹)", "State/UT Tax(₹)", "Cess(₹)", "ITC Availability"]
    m = guess_column_mapping(cols, GSTR2B)
    assert m == {"gstin": "GSTIN of supplier", "name": "Trade/Legal name", "invoice_no": "Invoice number",
                 "invoice_date": "Invoice Date", "taxable_value": "Taxable Value (₹)",
                 "igst": "Integrated Tax(₹)", "cgst": "Central Tax(₹)", "sgst": "State/UT Tax(₹)",
                 "invoice_value": "Invoice Value(₹)", "itc_availability": "ITC Availability"}


def test_wrong_columns_give_clear_message() -> None:
    raw = pd.DataFrame({"Foo": [1], "Bar": [2]})
    with pytest.raises(MappingError) as err:
        clean_register(raw, guess_column_mapping(list(raw.columns), BOOKS), BOOKS)
    assert any("Supplier GSTIN" in p for p in err.value.problems)
    assert any("tax column" in p for p in err.value.problems)


# ------------------------------------------------------------- messy files ------

def _messy_books() -> pd.DataFrame:
    return pd.DataFrame({
        "GSTIN": ["27AAPFU0939F1ZV", None, "27AAPFU0939F1ZX", " 27aapfu0939f1zv ", "", "27AAPFU0939F1ZV"],
        "Party Name": ["Alpha", None, "Alpha", "Alpha", "Grand Total", "Alpha"],
        "Bill No": ["A/001", None, "A/002", "A/003", None, None],
        "Bill Date": ["01-04-2026", None, "2026-04-02", "not a date", None, "03-04-2026"],
        "Taxable": ["1,000.00", None, "Rs 2000", "abc", "3000", "500"],
        "CGST": ["90", None, "(180)", "90", "270", "45"],
        "SGST": [90, None, "180", "90", "270", "45"],
    })


def test_messy_file_is_cleaned_and_problems_listed() -> None:
    raw = _messy_books()
    res = clean_register(raw, guess_column_mapping(list(raw.columns), BOOKS), BOOKS)
    d = res.data
    assert len(d) == 3                                       # blank row, total row, no-invoice row skipped
    assert d.loc[0, "taxable_value"] == 1000.0
    assert d.loc[1, "taxable_value"] == 2000.0 and d.loc[1, "cgst"] == -180.0
    assert d.loc[2, "gstin"] == "27AAPFU0939F1ZV"            # spaces/case fixed
    assert not d.loc[1, "gstin_valid"]                        # bad check character flagged
    problems = " | ".join(res.issues["Problem"])
    for text in ("Invalid GSTIN", "Not a number", "Date not recognised", "No invoice number"):
        assert text in problems
    assert res.issues["Row"].min() >= 2                       # real spreadsheet row numbers


def test_duplicates_pair_one_to_one() -> None:
    books = pd.DataFrame({"GSTIN": ["27AAPFU0939F1ZV"] * 2, "Invoice No": ["X1", "X1"],
                          "CGST": [10, 10], "SGST": [10, 10]})
    twob = pd.DataFrame({"GSTIN": ["27AAPFU0939F1ZV"], "Invoice No": ["x-1"], "CGST": [10], "SGST": [10]})
    r = run_reconciliation(books, twob)
    assert r.summary["counts"][MATCHED] == 1 and r.summary["counts"][IN_BOOKS_NOT_IN_2B] == 1


def test_gstin_typo_hint() -> None:
    books = pd.DataFrame({"GSTIN": ["27AAPFU0939F1ZV"], "Invoice No": ["Q-77"], "IGST": [500.0]})
    twob = pd.DataFrame({"GSTIN": ["29AAGCB7383J1Z4"], "Invoice No": ["Q77"], "IGST": [500.0]})
    r = run_reconciliation(books, twob)
    assert r.summary["counts"][IN_BOOKS_NOT_IN_2B] == 1
    assert "check GSTIN" in r.category(IN_BOOKS_NOT_IN_2B).loc[0, "Note"]


def test_parse_amounts() -> None:
    values, bad = parse_amounts(pd.Series(["1,23,456.50", "₹ 500", "(250)", "", None, "abc", 12]))
    assert values.tolist() == [123456.5, 500.0, -250.0, 0.0, 0.0, 0.0, 12.0]
    assert bad.tolist() == [False, False, False, False, False, True, False]


# ------------------------------------------------------------- file reading -----

def _portal_style_xlsx() -> bytes:
    """An Excel file shaped like the portal's GSTR-2B: title rows, then a two-row merged header."""
    wb = Workbook()
    wb.active.title = "Read me"
    ws = wb.create_sheet("B2B")
    ws.append(["Goods and Services Tax - GSTR-2B"])
    ws.append(["Taxable inward supplies received from registered persons"])
    ws.append([])
    ws.append(["GSTIN of supplier", "Trade/Legal name", "Invoice Details", None, None, None,
               "Taxable Value (₹)", "Tax Amount", None, None, "ITC Availability"])
    ws.append([None, None, "Invoice number", "Invoice type", "Invoice Date", "Invoice Value(₹)",
               None, "Integrated Tax(₹)", "Central Tax(₹)", "State/UT Tax(₹)", None])
    ws.append(["27AAPFU0939F1ZV", "ALPHA LLP", "A/001", "Regular", "01-04-2026", 1180, 1000, 0, 90, 90, "Yes"])
    ws.append(["27AAPFU0939F1ZV", "ALPHA LLP", "A/002", "Regular", "02-04-2026", 2360, 2000, 0, 180, 180, "No"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_read_portal_style_excel() -> None:
    raw = read_register(_portal_style_xlsx(), GSTR2B, filename="2b.xlsx")
    assert len(raw) == 2
    m = guess_column_mapping(list(raw.columns), GSTR2B)
    assert m["invoice_no"] == "Invoice number" and m["sgst"] == "State/UT Tax(₹)"
    assert m["gstin"] == "GSTIN of supplier" and m["taxable_value"] == "Taxable Value (₹)"
    cleaned = clean_register(raw, m, GSTR2B)
    assert cleaned.data["itc_availability"].tolist() == ["Yes", "No"]
    assert cleaned.data["source_row"].tolist() == [6, 7]


def test_read_csv_with_title_row() -> None:
    text = "Purchase Register Apr-Sep 2026\n\nGSTIN,Invoice No,CGST,SGST\n27AAPFU0939F1ZV,A1,9,9\n"
    raw = read_register(text.encode(), BOOKS, filename="books.csv")
    assert list(raw.columns) == ["GSTIN", "Invoice No", "CGST", "SGST"] and len(raw) == 1


def test_unsupported_file_type() -> None:
    from taxdesk.tabular import TableReadError
    with pytest.raises(TableReadError, match="xlsx"):
        read_register(b"%PDF", BOOKS, filename="x.pdf")


# ------------------------------------------------------------- speed ------------

def test_5000_plus_rows_in_a_few_seconds() -> None:
    """26 independent synthetic datasets stacked together: 5,200 book rows, 5,096 2B rows."""
    samples = [generate_gst_sample(seed) for seed in range(100, 126)]
    books = pd.concat([s.purchase_register for s in samples], ignore_index=True)
    twob = pd.concat([s.gstr2b for s in samples], ignore_index=True)
    start = time.perf_counter()
    r = run_reconciliation(books, twob)
    elapsed = time.perf_counter() - start
    assert len(books) == 5200
    assert r.summary["counts"][PROBABLE_MATCH] == 26 * PLANTED[PROBABLE_MATCH]
    assert r.summary["counts"][IN_BOOKS_NOT_IN_2B] == 26 * PLANTED[IN_BOOKS_NOT_IN_2B]
    assert elapsed < 5, f"took {elapsed:.1f}s"
