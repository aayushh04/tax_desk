"""ITR regime comparison page: enter income and deductions, compare both regimes, export.

Layout only. All logic lives in taxdesk.itr and taxdesk.exports.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from taxdesk.exports import itr_excel_report, itr_pdf_summary
from taxdesk.formatting import format_inr
from taxdesk.ids import is_valid_pan, mask_pan
from taxdesk.itr import NEW, OLD, REGIME_LABELS, IncomeInputs, compare_regimes, comparison_table
from taxdesk.rules import get_rule
from taxdesk.sample_data import generate_itr_clients
from ui_common import (Line, callout, footer, inr_text, note_heading, note_total, page_header, rupees, setup_page,
                       show_table, signoff, statement)

setup_page("ITR Regime Comparison")
DED = get_rule("income_tax.deductions")
MANUAL = "Enter my own figures"
SLAB_PLACES = {"Income in slab (₹)": 0, "Tax (₹)": 0}
SUBTOTALS = ("Income from salary", "Gross total income", "Taxable income", "Tax after rebate")


def computation_lines(table: pd.DataFrame, has_notes: bool) -> list[Line]:
    """The regime computation as statement lines: deductions bracketed, subtotals ruled, total double-ruled."""
    lines = []
    for i, row in enumerate(table.itertuples(index=False)):
        label, values = row[0], list(row[1:])
        if i == len(table) - 1:
            kind = "total"
        elif label.startswith("Less:"):
            kind = "less"
        elif label.startswith(SUBTOTALS):
            kind = "sub"
        else:
            kind = "line"
        note = 1 if label == "Tax on slabs" else (2 if has_notes and ("relief" in label or "Rebate" in label) else None)
        lines.append(Line(inr_text(label), values, note, kind))
    return lines


def rebate_working(regime: str, r) -> list[str]:
    """Plain-English working for the rebate (s.156) and marginal relief lines of one regime."""
    rule, label = get_rule(f"income_tax.{regime}_regime.rebate"), REGIME_LABELS[regime]
    limit = float(rule["income_limit"])
    if r.rebate:
        return [f"{label}: taxable income {rupees(r.taxable_income)} is within {rupees(limit)}, so the whole tax "
                f"on slabs ({rupees(r.slab_tax)}) is rebated, up to {rupees(rule['max_rebate'])}: rebate "
                f"{rupees(r.rebate)}."]
    if r.marginal_relief:
        excess = r.taxable_income - limit
        return [f"{label}: taxable income {rupees(r.taxable_income)} exceeds {rupees(limit)} by {rupees(excess)}. "
                f"Tax on slabs ({rupees(r.slab_tax)}) cannot be more than that excess, so marginal relief is "
                f"{rupees(r.marginal_relief)} and the tax before cess is {rupees(r.tax_after_rebate)}."]
    if r.taxable_income > limit:
        return [f"{label}: taxable income {rupees(r.taxable_income)} is above {rupees(limit)}, so no rebate"
                + (" or marginal relief applies." if rule.get("marginal_relief") else " applies.")]
    return []


def slab_rows(r) -> pd.DataFrame:
    """The slab working with bands in rupees and Indian grouping."""
    rows = [{"Slab": (f"Above {rupees(s.lower)}" if s.upper is None else f"{rupees(s.lower)} to {rupees(s.upper)}"),
             "Rate": f"{s.rate:.0%}", "Income in slab (₹)": float(s.income_in_slab), "Tax (₹)": float(s.tax)}
            for s in r.slabs]
    return pd.DataFrame(rows, columns=["Slab", "Rate", "Income in slab (₹)", "Tax (₹)"])


@st.cache_data(show_spinner=False)
def sample_clients() -> pd.DataFrame:
    """Three synthetic clients (safe to cache: no user data)."""
    return generate_itr_clients()


header_slot = st.empty()        # filled last, so the reference names the client in the result
results_slot = st.container()   # the result sits directly under the header

clients = sample_clients()
choices = [MANUAL, *[f"Sample: {r['name']} ({r['client_id']})" for _, r in clients.iterrows()]]
if st.session_state.pop("itr_load_sample", False):       # set by the Home page button
    st.session_state["itr_client_pick"] = choices[1]
st.session_state.setdefault("itr_client_pick", MANUAL)
stored = st.session_state.get("itr_result")
inputs_label = (f"Inputs: {stored[2] or 'client'} · gross salary {rupees(stored[0].gross_salary)}"
                if stored else "Client, income and deductions")

with st.expander(inputs_label, expanded=stored is None, icon=":material/tune:"):
    picked = st.selectbox("Client", choices, key="itr_client_pick")
    row = clients.iloc[choices.index(picked) - 1] if picked != MANUAL else None

    def val(field: str, default: float = 0.0) -> float:
        """Prefill from the chosen sample client, else the default."""
        return float(row[field]) if row is not None else default

    with st.form("itr_inputs", border=False):
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
        d123 = a.number_input(f"{DED['sec_123']['label']}, max ₹{format_inr(DED['sec_123']['limit'], 0)}",
                              min_value=0.0, step=5000.0, value=val("sec_123_80c"), format="%.0f")
        d126 = b.number_input(f"{DED['sec_126']['label']}, health insurance", min_value=0.0, step=1000.0,
                              value=val("sec_126_80d"), format="%.0f")
        a, b = st.columns(2)
        home = a.number_input(f"Home-loan interest, self-occupied (formerly s.24(b)), max ₹"
                              f"{format_inr(DED['home_loan_interest']['limit'], 0)}", min_value=0.0, step=5000.0,
                              value=val("home_loan_interest"), format="%.0f")
        hra = b.number_input("HRA exemption (formerly s.10(13A)), as worked out", min_value=0.0, step=5000.0,
                             value=val("hra_exemption"), format="%.0f")
        submitted = st.form_submit_button("Compare regimes", type="primary", width="stretch",
                                          icon=":material/compare_arrows:")

inputs = IncomeInputs(gross_salary, savings, fd, rent, municipal, d123, d126, home, hra, int(age))
if submitted:
    pan_clean = pan.strip().upper()
    st.session_state["itr_pan_warning"] = bool(pan_clean and not is_valid_pan(pan_clean))
    if st.session_state["itr_pan_warning"]:
        pan_clean = ""
    try:
        st.session_state["itr_result"] = (inputs, compare_regimes(inputs), name.strip(),
                                          mask_pan(pan_clean) if pan_clean else "")
        st.rerun()                                            # redraw with the result first, inputs folded
    except ValueError as exc:
        results_slot.error(str(exc))
        st.session_state.pop("itr_result", None)

stored = st.session_state.get("itr_result")
current = stored if stored and stored[0] == inputs else None
with results_slot:
    if current:
        _, cmp, client_name, pan_masked = current
        if st.session_state.get("itr_pan_warning"):
            st.warning("That PAN does not look valid (format AAAAA9999A). It was left out of the exports.")
        for w in cmp.warnings:
            st.warning(inr_text(w))
        notes = (rebate_working(NEW, cmp.new) + rebate_working(OLD, cmp.old)
                 + [inr_text(f"{REGIME_LABELS[NEW]}: {n}") for n in cmp.new.notes]
                 + [inr_text(f"{REGIME_LABELS[OLD]}: {n}") for n in cmp.old.notes])
        pick = REGIME_LABELS.get(cmp.cheaper)
        left, right = st.columns([1.5, 1], gap="medium")
        with left:
            statement("Computation of total income and tax", ["Particulars", REGIME_LABELS[NEW], REGIME_LABELS[OLD]],
                      computation_lines(comparison_table(cmp), bool(notes)), pick=pick)
        with right:
            if cmp.cheaper == "equal":
                callout("Both regimes give the same tax", rupees(cmp.new.total_tax), "Either regime can be chosen.")
            else:
                other = OLD if cmp.cheaper == NEW else NEW
                callout(f"Saving with the {REGIME_LABELS[cmp.cheaper].lower()}", rupees(cmp.saving),
                        f"{REGIME_LABELS[cmp.cheaper]} tax {rupees(getattr(cmp, cmp.cheaper).total_tax)} against "
                        f"{rupees(getattr(cmp, other).total_tax)} under the {REGIME_LABELS[other].lower()}. "
                        "See Note 1 for the slab working.", "agreed")
            safe_name = "".join(ch for ch in (client_name or "client") if ch.isalnum() or ch in " -_").strip() \
                or "client"
            st.download_button("Excel computation", itr_excel_report(cmp, inputs, client_name, pan_masked),
                               f"ITR_computation_{safe_name}.xlsx", type="primary", width="stretch",
                               icon=":material/download:",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.download_button("One-page PDF for client", itr_pdf_summary(cmp, client_name, pan_masked),
                               f"Regime_comparison_{safe_name}.pdf", mime="application/pdf", width="stretch",
                               icon=":material/picture_as_pdf:")

        note_heading(1, "Slab-by-slab working")
        a, b = st.columns(2)
        with a:
            st.markdown(f"**{REGIME_LABELS[NEW]}**")
            show_table(slab_rows(cmp.new), places=SLAB_PLACES)
            note_total([("Tax on slabs", cmp.new.slab_tax)], decimals=0)
        with b:
            st.markdown(f"**{REGIME_LABELS[OLD]}**")
            show_table(slab_rows(cmp.old), places=SLAB_PLACES)
            note_total([("Tax on slabs", cmp.old.slab_tax)], decimals=0)
        if notes:
            note_heading(2, "Rebate, marginal relief and other notes")
            st.markdown("\n".join(f"- {n}" for n in notes))
        signoff(client_name)
    elif stored:
        st.info("Inputs changed. Press **Compare regimes** to update.")

meta = " · ".join(x for x in ((current[3] if current else ""), f"Tax year {get_rule('meta.tax_year')}") if x)
page_header("Regime comparison",
            "Old vs new regime for a salaried individual, computed step by step. Yearly figures in rupees.",
            meta, current[2] if current else "", target=header_slot)

with st.expander("Rules used (from config/tax_rules_2026_27.yaml)", icon=":material/menu_book:"):
    st.markdown(inr_text(
        "- **New regime:** slabs 0-4L nil, 4-8L 5%, 8-12L 10%, 12-16L 15%, 16-20L 20%, 20-24L 25%, above 24L 30%; "
        "standard deduction Rs 75,000; rebate up to Rs 60,000 if taxable income <= Rs 12 lakh, "
        "with marginal relief just above.\n"
        "- **Old regime:** 0-2.5L nil, 2.5-5L 5%, 5-10L 20%, above 10L 30%; standard deduction Rs 50,000; "
        "rebate up to Rs 12,500 if taxable income <= Rs 5 lakh.\n"
        "- Cess 4%. Income and tax rounded to the nearest Rs 10. Surcharge, senior-citizen slabs and "
        "business income are out of scope."))
footer()
