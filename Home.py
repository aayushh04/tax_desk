"""TaxDesk home page: the contents of the report, with links and one-click sample data per module."""

import streamlit as st

from taxdesk.rules import get_rule
from ui_common import footer, intro_note, page_header, setup_page

setup_page("Home")

page_header("TaxDesk",
            "Working papers for a small Indian tax practice: GST reconciliation, regime comparison "
            "and mutual fund capital gains.", "Synthetic data only", f"Tax year {get_rule('meta.tax_year')}")
intro_note("Human in the loop.", "TaxDesk prepares, flags and exports working papers; a person reviews every "
           "figure and decides. It never files anything on any government portal or sends any email.")

MODULES = [
    ("gst", "pages/1_GST_Reconciliation.py", "GST reconciliation", "gst_load_sample",
     "Statement of input tax credit: purchase register against GSTR-2B, exact and fuzzy invoice matching, "
     "ITC at risk by supplier, a formatted Excel report and follow-up email drafts."),
    ("itr", "pages/2_ITR_Regime_Comparison.py", "Regime comparison", "itr_load_sample",
     "Computation of total income and tax under both regimes for a salaried client: deductions, rebate, "
     "marginal relief and cess. Excel computation sheet and a one-page client PDF."),
    ("mf", "pages/3_MF_Capital_Gains.py", "Mutual fund capital gains", "mf_load_sample",
     "Statement of capital gains: FIFO matching of redemptions, holding periods, 31 Jan 2018 grandfathering, "
     "estimated tax and a tax-harvesting plan. CSV template or CAS PDF."),
]

st.markdown("<h2 class='td-contents'>Contents</h2>", unsafe_allow_html=True)
for key, page, title, flag, text in MODULES:
    with st.container(key=f"td-index-row-{key}"):
        c_text, c_open, c_sample = st.columns([5.4, 1.5, 2], vertical_alignment="center")
        with c_text:
            st.markdown(f"<div class='td-idx-t'>{title}</div>", unsafe_allow_html=True)
            st.caption(text)
        c_open.page_link(page, label="Open", icon=":material/arrow_forward:")
        if c_sample.button("Load sample data", key=f"home_{flag}", width="stretch",
                           icon=":material/science:"):
            st.session_state[flag] = True
            st.switch_page(page)

st.write("")
with st.expander("Privacy and data", icon=":material/lock:"):
    st.markdown(
        "- The demo uses **synthetic data only**: fake suppliers, PANs, GSTINs and invoices.\n"
        "- Uploaded files are processed **in memory** for your session and are not saved.\n"
        "- PANs are shown masked (ABCDE\\*\\*\\*\\*F). CAS PDF passwords are used once and never stored.\n"
        "- Every rate, slab and date comes from one rules file (`config/tax_rules_2026_27.yaml`) "
        "with a source noted against each value.")
footer()
