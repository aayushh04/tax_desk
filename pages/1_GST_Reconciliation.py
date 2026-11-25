"""GST reconciliation page: upload -> map columns -> reconcile -> review -> export.

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
                         guess_column_mapping, read_register, reconcile, validate_mapping)
from taxdesk.rules import get_rule
from taxdesk.sample_data import generate_gst_sample
from taxdesk.tabular import TableReadError, excel_sheet_names
from ui_common import footer, rupees, setup_page, show_table

setup_page("GST Reconciliation", "🧾")
NOT_IN_FILE = "(not in file)"
FILE_LABELS = {BOOKS: "Purchase register", GSTR2B: "GSTR-2B (B2B)"}


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
    with st.expander(f"Column mapping: {FILE_LABELS[kind]}" + ("  (check this)" if problems else "  ✓"),
                     expanded=bool(problems)):
        st.caption("We guessed which column is which. Change any that are wrong.")
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
        st.caption("* required. At least one of IGST / CGST / SGST is also required.")
        st.dataframe(raw.head(5), hide_index=True, width="stretch")
    return mapping


# ============================================================== page ============

st.title("GST reconciliation")
st.write("Compare your **purchase register** with **GSTR-2B** to find input tax credit (ITC) at risk, "
         "amount mismatches and invoices you may have missed.")

if st.session_state.pop("gst_load_sample", False):       # set by the Home page button
    st.session_state["gst_source"] = "Sample data"
st.session_state.setdefault("gst_source", "Upload files")
source = st.segmented_control("Data source", ["Upload files", "Sample data"], key="gst_source",
                              label_visibility="collapsed")

books_raw = twob_raw = None
books_sig = twob_sig = ""
default_client = ""
if source == "Sample data":
    books_raw, twob_raw, default_client, books_xlsx, twob_xlsx = sample_data()
    books_sig, twob_sig = "sample-books", "sample-2b"
    st.info("Synthetic data: 30 fake suppliers, 200 invoices. Planted problems: 10 missing from 2B, "
            "6 missing from books, 8 amount differences, 5 invoice-number typos.")
    c1, c2 = st.columns(2)
    c1.download_button("Download sample purchase register", books_xlsx, "sample_purchase_register.xlsx",
                       width="stretch")
    c2.download_button("Download sample GSTR-2B", twob_xlsx, "sample_gstr2b.xlsx", width="stretch")
elif source == "Upload files":
    c1, c2 = st.columns(2)
    books_raw, books_sig = load_upload(BOOKS, c1)
    twob_raw, twob_sig = load_upload(GSTR2B, c2)
else:
    st.caption("Choose a data source above.")

if books_raw is not None and twob_raw is not None:
    st.subheader("1. Check columns")
    books_map = mapping_editor(BOOKS, books_raw, books_sig)
    twob_map = mapping_editor(GSTR2B, twob_raw, twob_sig)

    st.subheader("2. Settings")
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

    if st.button("Reconcile", type="primary", width="stretch"):
        try:
            with st.spinner("Matching invoices..."):
                books = clean_register(books_raw, books_map, BOOKS)
                twob = clean_register(twob_raw, twob_map, GSTR2B)
                result = reconcile(books, twob, tolerance, threshold)
                drafts = draft_supplier_emails(result, client_name or "[Your business name]")
                st.session_state["gst_result"] = {
                    "result": result, "drafts": drafts, "inputs": (books_sig, twob_sig),
                    "excel": gst_excel_report(result, client_name, drafts)}
        except MappingError as exc:
            for problem in exc.problems:
                st.error(problem)

# ============================================================== results =========

stored = st.session_state.get("gst_result")
if stored and books_raw is not None and stored["inputs"] == (books_sig, twob_sig):
    result, drafts = stored["result"], stored["drafts"]
    s = result.summary
    st.subheader("3. Results")

    m = st.columns(4)
    m[0].metric("ITC as per books", rupees(s["itc_as_per_books"]))
    m[1].metric("ITC as per GSTR-2B", rupees(s["itc_as_per_2b"]), help="Only rows where ITC is available")
    m[2].metric("ITC at risk", rupees(s["itc_at_risk"]),
                help="Tax on invoices missing from 2B, plus any shortfall where 2B shows less tax than books")
    m[3].metric("In 2B, not booked", rupees(s["itc_in_2b_not_booked"]),
                help="Credit available in 2B that is not in your books: check for missed entries")

    counts = s["counts"]
    c = st.columns(5)
    for col, key in zip(c, CATEGORY_ORDER):
        col.metric(CATEGORY_LABELS[key], f"{counts[key]:,}")

    n_issues = len(result.books_issues) + len(result.gstr2b_issues)
    if n_issues:
        with st.expander(f"⚠️ {n_issues} data problem(s) found while reading the files"):
            issues = pd.concat([result.books_issues.assign(File=FILE_LABELS[BOOKS]),
                                result.gstr2b_issues.assign(File=FILE_LABELS[GSTR2B])], ignore_index=True)
            show_table(issues[["File", "Row", "Column", "Problem", "Value"]])

    st.download_button("⬇️ Download Excel report", stored["excel"],
                       f"gst_reconciliation_{date.today():%Y%m%d}.xlsx", type="primary", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    search = st.text_input("Filter by supplier name or GSTIN", placeholder="Type to filter all tables")

    def filtered(df: pd.DataFrame) -> pd.DataFrame:
        if not search:
            return df
        mask = (df["Supplier Name"].str.contains(search, case=False, regex=False)
                | df["Supplier GSTIN"].str.contains(search, case=False, regex=False))
        return df[mask]

    tab_names = ["Supplier-wise", *[f"{CATEGORY_LABELS[k]} ({counts[k]})" for k in CATEGORY_ORDER],
                 f"Email drafts ({len(drafts)})"]
    tabs = st.tabs(tab_names)
    with tabs[0]:
        st.caption("Sorted by ITC at risk. Start your follow-ups from the top.")
        show_table(filtered(result.supplier_table))
    for tab, key in zip(tabs[1:6], CATEGORY_ORDER):
        with tab:
            table = filtered(result.category(key)[columns_for_category(key)])
            if table.empty:
                st.success("Nothing in this category.")
            else:
                show_table(table)
    with tabs[6]:
        st.info("These are drafts only. Copy one and send it from your own email. "
                "TaxDesk never sends emails or files anything.")
        if not drafts:
            st.success("No supplier follow-ups needed.")
        else:
            labels = [f"{d['Supplier Name']}: {rupees(d['ITC at Risk'])} at risk" for d in drafts]
            pick = st.selectbox("Supplier", range(len(drafts)), format_func=lambda i: labels[i])
            st.markdown("**Subject**")
            st.code(drafts[pick]["Subject"], language=None, wrap_lines=True)
            st.markdown("**Body**")
            st.code(drafts[pick]["Body"], language=None, wrap_lines=True)
elif stored and books_raw is not None:
    st.info("The files changed. Press **Reconcile** to see results for the new files.")

st.caption("Human in the loop: TaxDesk prepares and flags; you review and decide. "
           "Nothing is filed on the GST portal.")
footer()
