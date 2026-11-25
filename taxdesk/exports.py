"""Excel exports (pure Python + openpyxl, no Streamlit).

Every sheet gets: a coloured bold header row, frozen top row, filter buttons,
sensible column widths, Indian number format (12,34,567.00) and dd-mm-yyyy dates.
Files are built in memory and returned as bytes for the download button.
"""

from __future__ import annotations

import io
import math
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from taxdesk.capital_gains import CapitalGainsResult
from taxdesk.formatting import format_inr
from taxdesk.gst import CATEGORY_LABELS, CATEGORY_ORDER, ReconResult, columns_for_category, period_label
from taxdesk.itr import NEW, OLD, REGIME_LABELS, Comparison, IncomeInputs, comparison_table, slab_table
from taxdesk.rules import get_rule

# Excel number format with Indian grouping: 1,00,00,000.00 / 1,00,000.00 / 10,000.00
INR_FORMAT = r'[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00'
DATE_FORMAT = "dd-mm-yyyy"
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14)
BOLD = Font(bold=True)

GST_SHEET_NAMES: dict[str, str] = {
    "matched": "Matched",
    "amount_difference": "Amount Difference",
    "probable_match": "Needs Review",
    "in_books_not_in_2b": "Missing in 2B",
    "in_2b_not_in_books": "Not in Books",
}


def _cell_value(value: Any) -> Any:
    """Convert pandas/numpy values to plain Python values openpyxl understands (NaN/NaT -> blank)."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def write_table(ws: Worksheet, df: pd.DataFrame, start_row: int = 1, money_cols: Iterable[str] | None = None,
                wrap_cols: Iterable[str] = ()) -> None:
    """Write a DataFrame as a formatted table starting at `start_row` (header on that row)."""
    money = set(money_cols) if money_cols is not None else {
        c for c in df.columns if pd.api.types.is_float_dtype(df[c]) and c != "Similarity"}
    dates = {c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])}
    wrap = set(wrap_cols)
    for j, col in enumerate(df.columns, 1):
        cell = ws.cell(row=start_row, column=j, value=str(col))
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for i, row in enumerate(df.itertuples(index=False), start_row + 1):
        for j, (col, value) in enumerate(zip(df.columns, row), 1):
            cell = ws.cell(row=i, column=j, value=_cell_value(value))
            if col in money:
                cell.number_format = INR_FORMAT
            elif col in dates or isinstance(value, (datetime, date)):
                cell.number_format = DATE_FORMAT
            if col in wrap:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    for j, col in enumerate(df.columns, 1):
        sample = [len(str(col))] + [len(str(v)) for v in df[col].head(300).tolist() if v is not None]
        width = 60 if col in wrap else min(max(sample) + 2, 45)
        if col in money:
            width = max(width, 14)
        if col in dates:
            width = max(width, 12)
        ws.column_dimensions[get_column_letter(j)].width = width
    if len(df.columns):
        last = f"{get_column_letter(len(df.columns))}{start_row + max(len(df), 1)}"
        ws.auto_filter.ref = f"A{start_row}:{last}"


def _data_sheet(wb: Workbook, title: str, df: pd.DataFrame, **kwargs: Any) -> Worksheet:
    """Add a sheet holding one table, header in row 1 and frozen."""
    ws = wb.create_sheet(title[:31])
    write_table(ws, df, **kwargs)
    ws.freeze_panes = "A2"
    return ws


def dataframe_to_xlsx(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    """One formatted sheet as .xlsx bytes (used for sample-file downloads)."""
    wb = Workbook()
    wb.remove(wb.active)
    _data_sheet(wb, sheet_name, df)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def gst_excel_report(result: ReconResult, client_name: str = "",
                     email_drafts: list[dict[str, str]] | None = None) -> bytes:
    """Build the GST reconciliation workbook.

    Sheets: Summary, Supplier-wise, one per category, Email Drafts, Data Issues.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    s = result.summary
    ws["A1"] = "GST Reconciliation: Purchase Register vs GSTR-2B"
    ws["A1"].font = TITLE_FONT
    info = [("Client", client_name or "-"), ("Period", period_label(result.lines) or "-"),
            ("Generated on", datetime.now().strftime("%d-%m-%Y %H:%M")),
            ("Amount tolerance (Rs per tax head)", result.settings.get("tolerance")),
            ("Fuzzy match threshold (0-100)", result.settings.get("fuzzy_threshold"))]
    for r, (label, value) in enumerate(info, 3):
        ws.cell(row=r, column=1, value=label).font = BOLD
        ws.cell(row=r, column=2, value=value)

    figures = pd.DataFrame({
        "Measure": ["ITC as per books", "ITC as per GSTR-2B (available)", "ITC at risk",
                    "ITC in 2B not booked", "Invoices in books", "Invoices in 2B"],
        "Value": [s["itc_as_per_books"], s["itc_as_per_2b"], s["itc_at_risk"], s["itc_in_2b_not_booked"],
                  s["invoices_in_books"], s["invoices_in_2b"]],
    })
    write_table(ws, figures, start_row=10, money_cols=[])
    for r in range(11, 15):
        ws.cell(row=r, column=2).number_format = INR_FORMAT

    lines = result.lines
    cats = pd.DataFrame({
        "Category": [CATEGORY_LABELS[k] for k in CATEGORY_ORDER],
        "Invoices": [s["counts"][k] for k in CATEGORY_ORDER],
        "ITC at Risk": [round(float(lines.loc[lines["Category"] == k, "ITC at Risk"].sum()), 2)
                        for k in CATEGORY_ORDER],
        "Sheet": [GST_SHEET_NAMES[k] for k in CATEGORY_ORDER],
    })
    write_table(ws, cats, start_row=18, money_cols=["ITC at Risk"])
    ws.cell(row=25, column=1, value=get_rule("meta.disclaimer")).font = Font(italic=True, color="C00000")
    ws.cell(row=26, column=1, value="Prepared for review. This tool does not file anything on the GST portal.")
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 20
    ws.freeze_panes = "A2"

    _data_sheet(wb, "Supplier-wise", result.supplier_table)
    for key in CATEGORY_ORDER:
        _data_sheet(wb, GST_SHEET_NAMES[key], result.category(key)[columns_for_category(key)])
    if email_drafts:
        drafts = pd.DataFrame(email_drafts)[["Supplier GSTIN", "Supplier Name", "ITC at Risk", "Subject", "Body"]]
        _data_sheet(wb, "Email Drafts", drafts, wrap_cols=["Body"])
    issues = pd.concat([result.books_issues.assign(File="Purchase register"),
                        result.gstr2b_issues.assign(File="GSTR-2B")], ignore_index=True)
    if not issues.empty:
        _data_sheet(wb, "Data Issues", issues[["File", "Row", "Column", "Problem", "Value"]])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# =============================================================== ITR =============

_ITR_WORKING = {
    "Gross salary": "As entered",
    "Less: HRA exemption": "Old regime only; amount as entered",
    "Less: Standard deduction": "Rs 75,000 new / Rs 50,000 old (limited to salary)",
    "Income from salary": "Gross salary - HRA exemption - standard deduction",
    "Income from house property": "(Rent - municipal tax) x 70%, less home-loan interest (old only, max Rs 2 lakh)",
    "Income from other sources (interest)": "Savings interest + FD interest",
    "Gross total income": "Salary + house property + other sources",
    "Taxable income (rounded to Rs 10)": "Gross total income - deductions, rounded to nearest Rs 10",
    "Tax on slabs": "Each slab's rate on the income inside that slab (see Slab Working sheet)",
    "Less: Marginal relief": "New regime: tax cannot exceed income above Rs 12 lakh",
    "Tax after rebate": "Tax on slabs - rebate - marginal relief",
    "Total tax payable": "Tax after rebate + cess, rounded to nearest Rs 10",
}


def _itr_working(step: str) -> str:
    """Plain-words explanation for one computation step."""
    if step.startswith("Less: Section 123"):
        return "Old regime only; capped at Rs 1,50,000"
    if step.startswith("Less: Section 126"):
        return "Old regime only; health insurance, capped per rules file"
    if step.startswith("Less: Rebate"):
        return "Whole tax, up to Rs 60,000 (new, income <= 12 lakh) or Rs 12,500 (old, income <= 5 lakh)"
    if step.startswith("Add: Health"):
        return "4% of tax after rebate"
    return _ITR_WORKING.get(step, "")


def itr_excel_report(cmp: Comparison, inputs: IncomeInputs, client_name: str = "", pan_masked: str = "") -> bytes:
    """Computation workbook: side-by-side steps with a 'how it is calculated' column, slab tables, inputs."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Computation"
    ws["A1"] = f"Income-tax computation: Tax Year {get_rule('meta.tax_year')}"
    ws["A1"].font = TITLE_FONT
    for r, (label, value) in enumerate([("Client", client_name or "-"), ("PAN", pan_masked or "-"),
                                        ("Generated on", datetime.now().strftime("%d-%m-%Y %H:%M"))], 2):
        ws.cell(row=r, column=1, value=label).font = BOLD
        ws.cell(row=r, column=2, value=value)
    table = comparison_table(cmp)
    table["How it is calculated"] = table["Step"].map(_itr_working)
    start = 6
    write_table(ws, table, start_row=start, money_cols=[REGIME_LABELS[NEW], REGIME_LABELS[OLD]])
    last = start + len(table)
    for col in (1, 2, 3):
        ws.cell(row=last, column=col).font = BOLD
    cheaper_col = {NEW: 2, OLD: 3}.get(cmp.cheaper)
    if cheaper_col:
        for r in range(start + 1, last + 1):
            ws.cell(row=r, column=cheaper_col).fill = PatternFill("solid", fgColor="E2EFDA")
    ws.cell(row=last + 2, column=1, value=_verdict(cmp, html=False)).font = Font(bold=True, size=12, color="375623")
    row = last + 3
    for note in [*cmp.warnings, *(f"New: {n}" for n in cmp.new.notes), *(f"Old: {n}" for n in cmp.old.notes)]:
        ws.cell(row=row, column=1, value=note)
        row += 1
    ws.cell(row=row + 1, column=1, value=get_rule("meta.disclaimer")).font = Font(italic=True, color="C00000")
    for letter, width in zip("ABCD", (46, 16, 16, 80)):
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = f"A{start + 1}"

    slabs = wb.create_sheet("Slab Working")
    r = 1
    for result in (cmp.new, cmp.old):
        slabs.cell(row=r, column=1, value=REGIME_LABELS[result.regime]).font = TITLE_FONT
        t = slab_table(result)
        write_table(slabs, t, start_row=r + 1, money_cols=["Income in slab", "Tax"])
        r += len(t) + 4
    slabs.auto_filter.ref = None
    slabs.column_dimensions["A"].width = 34
    slabs.freeze_panes = "A2"

    labels = {"sec_123_80c": "Section 123 (formerly 80C)", "sec_126_80d": "Section 126 (formerly 80D)"}
    inp = pd.DataFrame({"Input": [labels.get(k, k.replace("_", " ").capitalize()) for k in vars(inputs)],
                        "Amount": [float(v) for v in vars(inputs).values()]})
    _data_sheet(wb, "Inputs", inp)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _verdict(cmp: Comparison, html: bool) -> str:
    """'New regime is cheaper by Rs 24,590.' (optionally with bold tags for the PDF)."""
    if cmp.cheaper == "equal":
        return "Both regimes result in the same tax."
    b, e = ("<b>", "</b>") if html else ("", "")
    return f"{b}{REGIME_LABELS[cmp.cheaper]}{e} is cheaper by {b}Rs {format_inr(cmp.saving, 0)}{e}."


def itr_pdf_summary(cmp: Comparison, client_name: str = "", pan_masked: str = "") -> bytes:
    """One-page A4 PDF for the client: side-by-side table, the recommendation and the disclaimer."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=14 * mm,
                            title="Tax regime comparison", author="TaxDesk")
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.grey)
    story = [Paragraph(f"Tax regime comparison: Tax Year {get_rule('meta.tax_year')}", styles["Title"]),
             Paragraph(f"<b>Client:</b> {escape(client_name or '-')} &nbsp;&nbsp; "
                       f"<b>PAN:</b> {escape(pan_masked or '-')} "
                       f"&nbsp;&nbsp; <b>Date:</b> {datetime.now():%d-%m-%Y}", styles["Normal"]),
             Spacer(1, 6 * mm)]

    table = comparison_table(cmp)
    data = [["Step", REGIME_LABELS[NEW], REGIME_LABELS[OLD]]]
    data += [[row["Step"], format_inr(row.iloc[1], 0), format_inr(row.iloc[2], 0)] for _, row in table.iterrows()]
    t = Table(data, colWidths=[95 * mm, 40 * mm, 40 * mm])
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
             ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
             ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
             ("FONTSIZE", (0, 0), (-1, -1), 9),
             ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F2F2F2")]),
             ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4)]
    cheaper_col = {NEW: 1, OLD: 2}.get(cmp.cheaper)
    if cheaper_col:
        style.append(("BACKGROUND", (cheaper_col, 1), (cheaper_col, -1), colors.HexColor("#E2EFDA")))
    t.setStyle(TableStyle(style))
    story += [t, Spacer(1, 6 * mm), Paragraph(_verdict(cmp, html=True) + " Based on the figures provided.",
                                              styles["Heading3"])]
    for note in [*cmp.warnings, *cmp.new.notes, *cmp.old.notes]:
        story.append(Paragraph(f"&bull; {note}", styles["Normal"]))
    story += [Spacer(1, 8 * mm),
              Paragraph("All amounts in rupees. Surcharge, senior-citizen slabs and business income are not "
                        "covered. Figures depend on the information supplied and must be verified against "
                        "Form 16, AIS/26AS and proofs before filing.", small),
              Spacer(1, 2 * mm),
              Paragraph(get_rule("meta.disclaimer"), small)]
    doc.build(story)
    return buf.getvalue()


# =============================================================== Capital gains ===

def cg_excel_report(result: CapitalGainsResult, harvest: pd.DataFrame | None = None) -> bytes:
    """Capital gains workbook: Summary, Lot-wise (FIFO), Scheme-wise, Open Holdings, optional harvest plan."""
    t = result.totals
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"Mutual fund capital gains: FY {result.fy}"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Generated on {datetime.now():%d-%m-%Y %H:%M}. FIFO basis, grandfathering applied where NAV given."
    figures = pd.DataFrame({"Measure": [
        "Total sale value", "Total cost (after grandfathering)", "Equity STCG (20%)", "Equity LTCG",
        "Equity LTCG after loss set-off", "LTCG exemption used", "Taxable equity LTCG (12.5%)",
        "Other LTCG (12.5%, no exemption)", "Gains taxed at slab rate (not in estimate)",
        "Estimated tax before cess", "Cess", "Estimated tax", "Unused tax-free LTCG this year",
        "Capital loss to carry forward"],
        "Amount": [t["sale_value"], t["cost_used"], t["equity_stcg"], t["equity_ltcg"],
                   t["equity_ltcg_after_set_off"], t["ltcg_exemption_used"], t["taxable_equity_ltcg"],
                   t["ltcg_12_5_no_exemption"], t["slab_rate_gains"], t["tax_before_cess"], t["cess"],
                   t["estimated_tax"], t["harvest_room"], t["loss_carried_forward"]]})
    write_table(ws, figures, start_row=4, money_cols=["Amount"])
    row = 4 + len(figures) + 2
    for w in result.warnings:
        ws.cell(row=row, column=1, value=w)
        row += 1
    ws.cell(row=row + 1, column=1, value=get_rule("meta.disclaimer")).font = Font(italic=True, color="C00000")
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 18
    ws.freeze_panes = "A2"
    lot_cols = ["Scheme", "ISIN", "Fund Type", "Buy Date", "Sell Date", "Units", "Buy NAV", "Sell NAV", "Cost",
                "FMV 31-Jan-2018", "Grandfathered", "Cost Used", "Sale Value", "Gain", "Holding Days", "Term",
                "Tax Treatment"]
    _data_sheet(wb, "Lot-wise (FIFO)", result.lots[lot_cols],
                money_cols=["Cost", "Cost Used", "Sale Value", "Gain"])
    _data_sheet(wb, "Scheme-wise", result.scheme_summary,
                money_cols=[c for c in result.scheme_summary.columns if c not in ("Scheme", "Fund Type", "Units Sold")])
    _data_sheet(wb, "Open Holdings", result.open_lots, money_cols=["Cost"])
    if harvest is not None and not harvest.empty:
        _data_sheet(wb, "Tax Harvesting", harvest,
                    money_cols=["Unrealised LTCG on Them", "Gain Booked", "Redemption Value"])
    if not result.issues.empty:
        _data_sheet(wb, "Data Issues", result.issues)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
