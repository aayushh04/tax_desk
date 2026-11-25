"""ITR regime comparison page: enter income and deductions, compare both regimes, export.

Layout only. All logic lives in taxdesk.itr and taxdesk.exports.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from taxdesk.exports import itr_excel_report, itr_pdf_summary
from taxdesk.formatting import format_inr
from taxdesk.ids import is_valid_pan, mask_pan
from taxdesk.itr import NEW, OLD, REGIME_LABELS, IncomeInputs, compare_regimes, comparison_table, slab_table
from taxdesk.rules import get_rule
from taxdesk.sample_data import generate_itr_clients
from ui_common import footer, rupees, setup_page, show_table

setup_page("ITR Regime Comparison", "📊")
DED = get_rule("income_tax.deductions")
MANUAL = "Enter my own figures"


@st.cache_data(show_spinner=False)
def sample_clients() -> pd.DataFrame:
    """Three synthetic clients (safe to cache: no user data)."""
    return generate_itr_clients()


st.title("ITR: old vs new regime")
st.write(f"Salaried individual, tax year **{get_rule('meta.tax_year')}**. Enter yearly figures in rupees. "
         "Both regimes are computed step by step and the cheaper one is highlighted.")

clients = sample_clients()
choices = [MANUAL, *[f"Sample: {r['name']} ({r['client_id']})" for _, r in clients.iterrows()]]
if st.session_state.pop("itr_load_sample", False):       # set by the Home page button
    st.session_state["itr_client_pick"] = choices[1]
st.session_state.setdefault("itr_client_pick", MANUAL)
picked = st.selectbox("Client", choices, key="itr_client_pick")
row = clients.iloc[choices.index(picked) - 1] if picked != MANUAL else None


def val(field: str, default: float = 0.0) -> float:
    """Prefill from the chosen sample client, else the default."""
    return float(row[field]) if row is not None else default


with st.form("itr_inputs"):
    st.markdown("**Client details**")
    a, b, c = st.columns(3)
    name = a.text_input("Client name", value=row["name"] if row is not None else "")
    pan = b.text_input("PAN (optional)", value=row["pan"] if row is not None else "", type="password",
                       help="Shown only masked (ABCDE****F). Not stored.")
    age = c.number_input("Age", min_value=18, max_value=100, value=int(val("age", 30)), step=1)

    st.markdown("**Income**")
    a, b, c = st.columns(3)
    gross_salary = a.number_input("Gross salary", min_value=0.0, step=10000.0, value=val("gross_salary"),
                                  format="%.0f")
    savings = b.number_input("Savings account interest", min_value=0.0, step=1000.0,
                             value=val("savings_interest"), format="%.0f")
    fd = c.number_input("FD interest", min_value=0.0, step=1000.0, value=val("fd_interest"), format="%.0f")
    a, b, _ = st.columns(3)
    rent = a.number_input("Rent received (let-out property)", min_value=0.0, step=5000.0,
                          value=val("rent_received"), format="%.0f")
    municipal = b.number_input("Municipal tax paid on it", min_value=0.0, step=1000.0,
                               value=val("municipal_tax_paid"), format="%.0f")

    st.markdown("**Old-regime deductions and exemptions**")
    a, b = st.columns(2)
    d123 = a.number_input(f"{DED['sec_123']['label']}, max Rs {format_inr(DED['sec_123']['limit'], 0)}",
                          min_value=0.0,
                          step=5000.0, value=val("sec_123_80c"), format="%.0f")
    d126 = b.number_input(f"{DED['sec_126']['label']}, health insurance", min_value=0.0, step=1000.0,
                          value=val("sec_126_80d"), format="%.0f")
    a, b = st.columns(2)
    home = a.number_input(f"Home-loan interest, self-occupied (formerly s.24(b)), max Rs "
                          f"{format_inr(DED['home_loan_interest']['limit'], 0)}", min_value=0.0, step=5000.0,
                          value=val("home_loan_interest"), format="%.0f")
    hra = b.number_input("HRA exemption (formerly s.10(13A)), as worked out", min_value=0.0, step=5000.0,
                         value=val("hra_exemption"), format="%.0f")
    submitted = st.form_submit_button("Compare regimes", type="primary", width="stretch")

inputs = IncomeInputs(gross_salary, savings, fd, rent, municipal, d123, d126, home, hra, int(age))
if submitted:
    pan_clean = pan.strip().upper()
    if pan_clean and not is_valid_pan(pan_clean):
        st.warning("That PAN does not look valid (format AAAAA9999A). It will not be printed.")
        pan_clean = ""
    try:
        st.session_state["itr_result"] = (inputs, compare_regimes(inputs), name.strip(), mask_pan(pan_clean)
                                          if pan_clean else "")
    except ValueError as exc:
        st.error(str(exc))
        st.session_state.pop("itr_result", None)

stored = st.session_state.get("itr_result")
if stored and stored[0] == inputs:
    _, cmp, client_name, pan_masked = stored
    st.subheader("Result" + (f": {client_name}" if client_name else "") + (f" ({pan_masked})" if pan_masked else ""))
    for w in cmp.warnings:
        st.warning(w)

    m = st.columns(3)
    m[0].metric(REGIME_LABELS[NEW], rupees(cmp.new.total_tax))
    m[1].metric(REGIME_LABELS[OLD], rupees(cmp.old.total_tax))
    if cmp.cheaper == "equal":
        m[2].metric("Saving", "₹0", help="Both regimes give the same tax")
        st.info("Both regimes give the same tax.")
    else:
        m[2].metric("You save with", REGIME_LABELS[cmp.cheaper], delta=rupees(cmp.saving), delta_color="normal")
        st.success(f"**{REGIME_LABELS[cmp.cheaper]}** is cheaper by **{rupees(cmp.saving)}**.")

    table = comparison_table(cmp)
    highlight = REGIME_LABELS.get(cmp.cheaper)
    styled = table.style.format({REGIME_LABELS[NEW]: lambda v: format_inr(v, 0),
                                 REGIME_LABELS[OLD]: lambda v: format_inr(v, 0)})
    if highlight:
        styled = styled.set_properties(subset=[highlight], **{"background-color": "rgba(76,175,80,0.18)",
                                                               "font-weight": "600"})
    styled = styled.apply(lambda r: ["font-weight: 700" if r["Step"] == "Total tax payable" else ""
                                     for _ in r], axis=1)
    st.dataframe(styled, hide_index=True, width="stretch", height=(len(table) + 1) * 35 + 3)

    with st.expander("Slab-by-slab working"):
        a, b = st.columns(2)
        with a:
            st.markdown(f"**{REGIME_LABELS[NEW]}**")
            show_table(slab_table(cmp.new))
        with b:
            st.markdown(f"**{REGIME_LABELS[OLD]}**")
            show_table(slab_table(cmp.old))
    notes = [f"New: {n}" for n in cmp.new.notes] + [f"Old: {n}" for n in cmp.old.notes]
    if notes:
        with st.expander("Notes on this computation"):
            for n in notes:
                st.markdown(f"- {n}")

    safe_name = "".join(ch for ch in (client_name or "client") if ch.isalnum() or ch in " -_").strip() or "client"
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Excel computation", itr_excel_report(cmp, inputs, client_name, pan_masked),
                       f"ITR_computation_{safe_name}.xlsx", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d2.download_button("⬇️ One-page PDF for client", itr_pdf_summary(cmp, client_name, pan_masked),
                       f"Regime_comparison_{safe_name}.pdf", mime="application/pdf", width="stretch")
elif stored:
    st.info("Inputs changed. Press **Compare regimes** to update.")

with st.expander("Rules used (from config/tax_rules_2026_27.yaml)"):
    st.markdown(
        "- **New regime:** slabs 0-4L nil, 4-8L 5%, 8-12L 10%, 12-16L 15%, 16-20L 20%, 20-24L 25%, above 24L 30%; "
        "standard deduction Rs 75,000; rebate up to Rs 60,000 if taxable income <= Rs 12 lakh, "
        "with marginal relief just above.\n"
        "- **Old regime:** 0-2.5L nil, 2.5-5L 5%, 5-10L 20%, above 10L 30%; standard deduction Rs 50,000; "
        "rebate up to Rs 12,500 if taxable income <= Rs 5 lakh.\n"
        "- Cess 4%. Income and tax rounded to the nearest Rs 10. Surcharge, senior-citizen slabs and "
        "business income are out of scope.")
footer()
