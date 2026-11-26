"""Mutual fund capital gains page: load transactions -> confirm schemes -> FIFO gains -> export.

Layout only. All logic lives in taxdesk.capital_gains and taxdesk.exports.
Files and CAS passwords are used in memory only; the password field is cleared after use.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from taxdesk.capital_gains import (FUND_TYPES, TransactionsError, cas_available, clean_transactions,
                                   compute_capital_gains, fy_label, harvest_plan, parse_cas_pdf, scheme_list)
from taxdesk.exports import cg_excel_report
from taxdesk.rules import get_rule
from taxdesk.sample_data import generate_mf_sample, mf_template
from taxdesk.tabular import TableReadError, read_table
from ui_common import (Line, callout, footer, inr_text, note_heading, note_total, page_header, rupees, setup_page,
                       show_table, signoff, statement, table_height)

setup_page("MF Capital Gains")
DEFAULT_FY = get_rule("app_settings.default_financial_year")
SOURCES = ["Upload CSV / Excel", "Sample data"] + (["CAS PDF"] if cas_available() else [])


SCHEME_WIDTHS = {"Scheme": 300, "Plan": 120}


def split_plan(df: pd.DataFrame) -> pd.DataFrame:
    """Show 'Fund name - Direct Growth' as Scheme + Plan, so the fund name fits without clipping."""
    if "Scheme" not in df.columns or df.empty:
        return df
    parts = df["Scheme"].astype(str).str.rsplit(" - ", n=1, expand=True)
    if parts.shape[1] < 2:
        return df
    out = df.copy()
    out["Scheme"] = parts[0]
    out.insert(int(out.columns.get_loc("Scheme")) + 1, "Plan", parts[1].fillna(""))
    return out


@st.cache_data(show_spinner=False)
def sample() -> tuple[pd.DataFrame, dict[str, float]]:
    """Synthetic 2016-2026 history (safe to cache: no user data)."""
    mf = generate_mf_sample()
    return mf.transactions, mf.fmv_31jan2018


header_slot = st.empty()        # filled last with the year and source of the result
results_slot = st.container()   # results sit directly under the header

if st.session_state.pop("mf_load_sample", False):        # set by the Home page button
    st.session_state["mf_source"] = "Sample data"
st.session_state.setdefault("mf_source", SOURCES[0])
label_used = st.session_state.get("mf_inputs_label") or "Load transactions and confirm schemes"

raw: pd.DataFrame | None = None
signature = ""
default_fmv: dict[str, float] = {}
store = st.session_state.setdefault("mf_loaded", {})            # this browser session only
txns = None
with st.expander(label_used, expanded=label_used.startswith("Load"), icon=":material/tune:"):
    source = st.segmented_control("Data source", SOURCES, key="mf_source", label_visibility="collapsed")
    t1, t2 = st.columns(2)
    t1.download_button("Download blank template (CSV)", mf_template().to_csv(index=False), "mf_template.csv",
                       mime="text/csv", width="stretch", icon=":material/table_view:")
    t2.download_button("Download synthetic example (CSV)",
                       sample()[0].to_csv(index=False, date_format="%Y-%m-%d"), "mf_example.csv",
                       mime="text/csv", width="stretch", icon=":material/table_view:")

    if source == "Sample data":
        raw, default_fmv = sample()
        signature = "sample"
        st.info("Synthetic history: 4 fictional schemes (2 equity, 1 debt, 1 fund-of-funds), SIPs from 2016, "
                "partial redemptions in several years. 31 Jan 2018 NAVs are prefilled.")
    elif source == "Upload CSV / Excel":
        file = st.file_uploader("Transactions file", type=["csv", "xlsx"], key="mf_upload",
                                help="Use the template columns: " + ", ".join(mf_template().columns))
        if file is not None:
            data = file.getvalue()
            signature = f"{file.name}|{len(data)}"
            if store.get("sig") != signature:
                try:
                    store.update(sig=signature, raw=read_table(data, filename=file.name,
                                                               expected_headers=list(mf_template().columns)))
                except TableReadError as exc:
                    st.error(str(exc))
                    signature = ""
            raw = store.get("raw") if signature else None
    elif source == "CAS PDF":
        st.caption("CAMS/KFintech detailed CAS. The password is used once to open the file and is never stored.")
        with st.form("cas_form", clear_on_submit=True):
            pdf = st.file_uploader("CAS PDF", type=["pdf"])
            password = st.text_input("PDF password", type="password")
            go = st.form_submit_button("Read CAS", type="primary")
        if go and pdf is not None:
            try:
                with st.spinner("Reading CAS..."):
                    store.update(sig=f"cas|{pdf.name}|{pdf.size}", raw=parse_cas_pdf(pdf.getvalue(), password))
            except TransactionsError as exc:
                st.error(str(exc))
            del password
        if str(store.get("sig", "")).startswith("cas|"):
            signature, raw = store["sig"], store["raw"]
            st.success(f"{len(raw):,} transactions read from the CAS. Check the fund types below.")

    if raw is not None:
        try:
            txns = clean_transactions(raw)
        except TransactionsError as exc:
            st.error(str(exc))
        if txns is not None and txns.data.empty:
            st.error("No usable transactions found in the file.")
            txns = None

    if txns is not None:
        if not txns.issues.empty:
            st.warning(f"{len(txns.issues)} row(s) had problems and were skipped or adjusted:")
            show_table(txns.issues)
        st.subheader("Schemes")
        schemes = scheme_list(txns)
        schemes["NAV on 31-Jan-2018"] = schemes["key"].map(default_fmv).astype(float)
        schemes["Current NAV"] = float("nan")
        st.caption("Set the correct fund type. Enter the 31 Jan 2018 NAV for equity schemes bought before "
                   "Feb 2018 (grandfathering). Current NAV is optional and only used for the tax-harvesting plan.")
        edited = st.data_editor(
            schemes, key=f"mf_schemes_{signature}", hide_index=True, width="stretch",
            column_order=["scheme", "fund_type", "needs_fmv", "NAV on 31-Jan-2018", "Current NAV"],
            column_config={
                "scheme": st.column_config.TextColumn("Scheme", disabled=True),
                "fund_type": st.column_config.SelectboxColumn("Fund type", options=list(FUND_TYPES), required=True),
                "needs_fmv": st.column_config.CheckboxColumn("Bought before Feb 2018?", disabled=True),
                "NAV on 31-Jan-2018": st.column_config.NumberColumn(min_value=0.0, format="%.4f"),
                "Current NAV": st.column_config.NumberColumn(min_value=0.0, format="%.4f"),
            })

# Fold the inputs once transactions are loaded (the new label makes a new, collapsed expander).
label_now = (f"Inputs: {source.lower()} · {txns.data['key'].nunique()} schemes · {len(txns.data):,} transactions"
             if txns is not None else "Load transactions and confirm schemes")
if label_now != label_used:
    st.session_state["mf_inputs_label"] = label_now
    st.rerun()

fy = DEFAULT_FY
if txns is not None:
    fund_types = dict(zip(edited["key"], edited["fund_type"]))
    fmv = {k: float(v) for k, v in zip(edited["key"], edited["NAV on 31-Jan-2018"]) if pd.notna(v) and v > 0}
    current = {k: float(v) for k, v in zip(edited["key"], edited["Current NAV"]) if pd.notna(v) and v > 0}
    sells = txns.data[txns.data["type"] == "sell"]
    years = sorted({fy_label(d) for d in sells["date"]} | {DEFAULT_FY}, reverse=True)

    with results_slot:
        fy = st.selectbox("Financial year", years, index=years.index(DEFAULT_FY))
        result = compute_capital_gains(txns, fy, fund_types, fmv)
        t = result.totals
        missing_fmv = bool((result.lots.get("Grandfathered", pd.Series(dtype=str)) == "FMV missing").any())
        show_harvest = fy == DEFAULT_FY and t["harvest_room"] > 0
        harvest = harvest_plan(result, current, date.today(), fmv) if show_harvest and current else None
        for w in result.warnings:
            st.warning(inr_text(w))

        lines = [
            Line("Equity short-term gains (20%)", [t["equity_stcg"]], 1),
            Line("Equity long-term gains", [t["equity_ltcg"]], 1),
            Line(f"Less: exemption (first {rupees(get_rule('capital_gains.equity.ltcg_exemption'))})",
                 [t["ltcg_exemption_used"]], None, "less"),
            Line("Taxable equity long-term gains (12.5%)", [t["taxable_equity_ltcg"]], None, "sub"),
            Line("Other long-term gains (12.5%, no exemption)", [t["ltcg_12_5_no_exemption"]], 1),
            Line("Estimated tax on these gains, with 4% cess", [t["estimated_tax"]], None, "total"),
            Line("Gains taxed at slab rate (not in the estimate)", [t["slab_rate_gains"]], 1, "memo"),
        ]
        if show_harvest:
            lines.append(Line("Equity long-term gains still tax-free this year", [t["harvest_room"]], 4, "memo"))
        left, right = st.columns([1.5, 1], gap="medium")
        with left:
            statement(f"Statement of capital gains, FY {fy}", ["Particulars", "Amount (₹)"], lines)
            st.caption("The rebate under s.156 (formerly 87A) cannot be used against tax on equity STCG/LTCG.")
        with right:
            chips = [("Lots sold", len(result.lots), "neutral"), ("Open lots", len(result.open_lots), "neutral")]
            if missing_fmv:
                chips.append(("31 Jan 2018 NAV missing", None, "review"))
            callout("Estimated tax on capital gains", rupees(t["estimated_tax"]),
                    "Equity STCG, taxable LTCG and other 12.5% LTCG, plus cess. See Note 1 for each lot.",
                    "neutral", chips)
            st.download_button("Download Excel report", cg_excel_report(result, harvest),
                               f"MF_capital_gains_FY{fy}.xlsx", type="primary", width="stretch",
                               icon=":material/download:",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        cols = ["Gain", "Scheme", "Sell Date", "Tax Treatment", "Fund Type", "Buy Date", "Units", "Buy NAV",
                "Sell NAV", "Cost", "FMV 31-Jan-2018", "Cost Used", "Sale Value", "Holding Days", "Term"]
        note_heading(1, "Lot-wise gains (FIFO)", f"{len(result.lots)} lots")
        if result.lots.empty:
            st.success(f"No redemptions in FY {fy}.")
        else:
            lots = split_plan(result.lots[cols].copy())
            lots["FMV 31-Jan-2018"] = lots["FMV 31-Jan-2018"].map(lambda v: f"{v:,.4f}" if pd.notna(v) else "n/a")
            show_table(lots, height=table_height(len(lots)), widths=SCHEME_WIDTHS,
                       labels={"Gain": "Gain (₹)", "Cost": "Cost (₹)", "Cost Used": "Cost used (₹)",
                               "Sale Value": "Sale value (₹)"})
            note_total([("Total gain on lots sold, before set-off", round(float(lots["Gain"].sum()), 2))])
        note_heading(2, "Scheme-wise summary", f"{len(result.scheme_summary)} schemes")
        summary = split_plan(result.scheme_summary)
        summary = summary[["Total Gain", "Scheme", *[c for c in summary.columns if c not in ("Scheme", "Total Gain")]]]
        show_table(summary, widths=SCHEME_WIDTHS)
        note_heading(3, "Open holdings after this year", f"{len(result.open_lots)} lots")
        open_lots = split_plan(result.open_lots)
        open_lots = open_lots[["Cost", "Scheme", *[c for c in open_lots.columns if c not in ("Scheme", "Cost")]]]
        show_table(open_lots, height=table_height(len(open_lots)), widths=SCHEME_WIDTHS)
        if show_harvest:
            note_heading(4, "Tax-harvesting plan")
            st.info(f"You can still book about **{rupees(t['harvest_room'])}** of equity long-term gains tax-free "
                    f"in FY {fy} (redeem and reinvest). Only units held more than 12 months qualify, and FIFO means "
                    "the oldest units are sold first. Exit loads and the reinvestment date resetting your holding "
                    "period also matter.")
            if harvest is not None:
                show_table(harvest)
            else:
                st.caption("Enter a Current NAV in the scheme table (Inputs) to see how many units to redeem.")
        signoff()

page_header("Mutual fund capital gains",
            "FIFO lot matching, holding periods, 31 Jan 2018 grandfathering and estimated tax",
            f"FY {fy}" + (f" · {source.lower()}" if txns is not None else ""), target=header_slot)
footer()
