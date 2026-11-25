"""Tests for the Excel and PDF exports."""

import io

import pdfplumber
from openpyxl import load_workbook

from taxdesk.capital_gains import clean_transactions, compute_capital_gains
from taxdesk.exports import (GST_SHEET_NAMES, INR_FORMAT, cg_excel_report, gst_excel_report,
                             itr_excel_report, itr_pdf_summary)
from taxdesk.gst import draft_supplier_emails, run_reconciliation
from taxdesk.itr import compare_regimes, inputs_from_row
from taxdesk.sample_data import generate_gst_sample, generate_itr_clients, generate_mf_sample


def test_gst_workbook_structure_and_formatting() -> None:
    s = generate_gst_sample()
    result = run_reconciliation(s.purchase_register, s.gstr2b)
    drafts = draft_supplier_emails(result, s.client_name)
    wb = load_workbook(io.BytesIO(gst_excel_report(result, s.client_name, drafts)))

    assert wb.sheetnames[:2] == ["Summary", "Supplier-wise"]
    for key, name in GST_SHEET_NAMES.items():
        ws = wb[name]
        assert ws.max_row - 1 == result.summary["counts"][key]     # one row per invoice + header
        assert ws.freeze_panes == "A2"
        assert ws["A1"].font.bold
    assert "Email Drafts" in wb.sheetnames

    missing = wb["Missing in 2B"]
    headers = [c.value for c in missing[1]]
    assert missing.cell(row=2, column=headers.index("Books Total Tax") + 1).number_format == INR_FORMAT
    assert missing.cell(row=2, column=headers.index("Books Invoice Date") + 1).number_format == "dd-mm-yyyy"
    summary_text = " ".join(str(c.value) for row in wb["Summary"].iter_rows() for c in row if c.value)
    assert "Not tax advice" in summary_text


def test_itr_excel_and_one_page_pdf() -> None:
    row = generate_itr_clients().iloc[1]
    inputs = inputs_from_row(row)
    cmp = compare_regimes(inputs)
    wb = load_workbook(io.BytesIO(itr_excel_report(cmp, inputs, row["name"], "VTAPP****D")))
    assert wb.sheetnames == ["Computation", "Slab Working", "Inputs"]
    text = " ".join(str(c.value) for r in wb["Computation"].iter_rows() for c in r if c.value)
    assert "Section 123 (formerly 80C)" in text and "Old regime is cheaper" in text

    pdf = pdfplumber.open(io.BytesIO(itr_pdf_summary(cmp, "A & B <Test>", "VTAPP****D")))
    assert len(pdf.pages) == 1
    page = pdf.pages[0].extract_text()
    assert "A & B <Test>" in page and "VTAPP****D" in page and "Not tax advice" in page
    assert row["pan"] not in page                                   # full PAN never printed


def test_capital_gains_workbook() -> None:
    mf = generate_mf_sample()
    r = compute_capital_gains(clean_transactions(mf.transactions), "2026-27", fmv_per_unit=mf.fmv_31jan2018)
    wb = load_workbook(io.BytesIO(cg_excel_report(r)))
    assert wb.sheetnames == ["Summary", "Lot-wise (FIFO)", "Scheme-wise", "Open Holdings"]
    assert wb["Lot-wise (FIFO)"].max_row - 1 == len(r.lots)
    assert wb["Lot-wise (FIFO)"].freeze_panes == "A2"
