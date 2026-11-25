"""TaxDesk home page: what each module does, links, and one-click sample data."""

import streamlit as st

from taxdesk.rules import get_rule
from ui_common import footer, setup_page

setup_page("Home", "🧾")

st.title("🧾 TaxDesk")
st.markdown(f"Automation for the repetitive work in a small Indian tax practice: GST reconciliation, "
            f"regime comparison and mutual fund capital gains. Rules for tax year "
            f"**{get_rule('meta.tax_year')}**.")
st.info("**Human in the loop.** TaxDesk prepares, flags and exports working papers; a person reviews every "
        "figure and decides. It never files anything on any government portal or sends any email.")

MODULES = [
    ("pages/1_GST_Reconciliation.py", "🧾 GST reconciliation", "gst_load_sample",
     "Match the purchase register with GSTR-2B: exact and fuzzy invoice matching, amount differences, "
     "ITC at risk by supplier, a formatted Excel report and follow-up email drafts."),
    ("pages/2_ITR_Regime_Comparison.py", "📊 ITR regime comparison", "itr_load_sample",
     "Old vs new regime for a salaried client, step by step: deductions, rebate, marginal relief and cess. "
     "Excel computation sheet and a one-page client PDF."),
    ("pages/3_MF_Capital_Gains.py", "📈 MF capital gains", "mf_load_sample",
     "FIFO matching of redemptions, holding periods, 31 Jan 2018 grandfathering, STCG/LTCG totals, "
     "estimated tax and a tax-harvesting hint. CSV template or CAS PDF."),
]

cols = st.columns(3)
for col, (page, title, flag, text) in zip(cols, MODULES):
    with col.container(border=True):
        st.subheader(title)
        st.write(text)
        st.page_link(page, label="Open", icon="➡️")
        if st.button("Load sample data", key=f"home_{flag}", width="stretch"):
            st.session_state[flag] = True
            st.switch_page(page)

with st.expander("Privacy and data"):
    st.markdown(
        "- The demo uses **synthetic data only**: fake suppliers, PANs, GSTINs and invoices.\n"
        "- Uploaded files are processed **in memory** for your session and are not saved.\n"
        "- PANs are shown masked (ABCDE\\*\\*\\*\\*F). CAS PDF passwords are used once and never stored.\n"
        "- Every rate, slab and date comes from one rules file (`config/tax_rules_2026_27.yaml`) "
        "with a source noted against each value.")
footer()
