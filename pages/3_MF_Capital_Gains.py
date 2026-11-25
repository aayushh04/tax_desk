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
from ui_common import footer, rupees, setup_page, show_table

setup_page("MF Capital Gains", "📈")
DEFAULT_FY = get_rule("app_settings.default_financial_year")
SOURCES = ["Upload CSV / Excel", "Sample data"] + (["CAS PDF"] if cas_available() else [])


@st.cache_data(show_spinner=False)
def sample() -> tuple[pd.DataFrame, dict[str, float]]:
    """Synthetic 2016-2026 history (safe to cache: no user data)."""
    mf = generate_mf_sample()
    return mf.transactions, mf.fmv_31jan2018


st.title("Mutual fund capital gains")
st.write("FIFO matching of redemptions against purchases, holding periods, 31 Jan 2018 grandfathering "
         "and an estimate of capital-gains tax for the year.")

if st.session_state.pop("mf_load_sample", False):        # set by the Home page button
    st.session_state["mf_source"] = "Sample data"
st.session_state.setdefault("mf_source", SOURCES[0])
source = st.segmented_control("Data source", SOURCES, key="mf_source", label_visibility="collapsed")

t1, t2 = st.columns(2)
t1.download_button("Download blank template (CSV)", mf_template().to_csv(index=False), "mf_template.csv",
                   mime="text/csv", width="stretch")
t2.download_button("Download synthetic example (CSV)", sample()[0].to_csv(index=False, date_format="%Y-%m-%d"),
                   "mf_example.csv", mime="text/csv", width="stretch")

raw: pd.DataFrame | None = None
signature = ""
default_fmv: dict[str, float] = {}
store = st.session_state.setdefault("mf_loaded", {})            # this browser session only

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
        txns = None
    if txns is not None and txns.data.empty:
        st.error("No usable transactions found in the file.")
        txns = None

    if txns is not None:
        if not txns.issues.empty:
            with st.expander(f"⚠️ {len(txns.issues)} row(s) had problems"):
                show_table(txns.issues)

        st.subheader("1. Confirm schemes")
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
        fund_types = dict(zip(edited["key"], edited["fund_type"]))
        fmv = {k: float(v) for k, v in zip(edited["key"], edited["NAV on 31-Jan-2018"]) if pd.notna(v) and v > 0}
        current = {k: float(v) for k, v in zip(edited["key"], edited["Current NAV"]) if pd.notna(v) and v > 0}

        sells = txns.data[txns.data["type"] == "sell"]
        years = sorted({fy_label(d) for d in sells["date"]} | {DEFAULT_FY}, reverse=True)
        fy = st.selectbox("2. Financial year", years, index=years.index(DEFAULT_FY))

        result = compute_capital_gains(txns, fy, fund_types, fmv)
        t = result.totals
        st.subheader(f"3. Capital gains for FY {fy}")
        m = st.columns(4)
        m[0].metric("Equity STCG (20%)", rupees(t["equity_stcg"]))
        m[1].metric("Equity LTCG", rupees(t["equity_ltcg"]))
        m[2].metric("LTCG exemption used", rupees(t["ltcg_exemption_used"]),
                    help=f"First Rs {get_rule('capital_gains.equity.ltcg_exemption'):,} of equity LTCG is tax-free")
        m[3].metric("Estimated tax (incl. cess)", rupees(t["estimated_tax"]),
                    help="Equity STCG + taxable LTCG + other 12.5% LTCG, plus 4% cess. Excludes slab-rate gains.")
        m = st.columns(3)
        m[0].metric("Other LTCG (12.5%, no exemption)", rupees(t["ltcg_12_5_no_exemption"]))
        m[1].metric("Gains taxed at slab rate", rupees(t["slab_rate_gains"]),
                    help="Debt funds bought on/after 1 Apr 2023, and short-term debt/other gains")
        m[2].metric("Unused tax-free LTCG", rupees(t["harvest_room"]))
        for w in result.warnings:
            st.warning(w)
        st.caption("The rebate under s.156 (formerly 87A) cannot be used against tax on equity STCG/LTCG.")

        harvest = None
        if fy == DEFAULT_FY and t["harvest_room"] > 0:
            st.info(f"💡 **Tax-harvesting hint:** you can still book about **{rupees(t['harvest_room'])}** of "
                    f"equity long-term gains tax-free in FY {fy} (redeem and reinvest). Only units held more "
                    "than 12 months qualify, and FIFO means the oldest units are sold first. Exit loads and "
                    "the reinvestment date resetting your holding period also matter.")
            if current:
                harvest = harvest_plan(result, current, date.today(), fmv)
                show_table(harvest)
            else:
                st.caption("Enter a Current NAV in the scheme table to see how many units to redeem.")

        tabs = st.tabs([f"Lot-wise ({len(result.lots)})", "Scheme-wise", f"Open holdings ({len(result.open_lots)})"])
        with tabs[0]:
            cols = ["Scheme", "Fund Type", "Buy Date", "Sell Date", "Units", "Buy NAV", "Sell NAV", "Cost",
                    "FMV 31-Jan-2018", "Cost Used", "Sale Value", "Gain", "Holding Days", "Term", "Tax Treatment"]
            if result.lots.empty:
                st.success(f"No redemptions in FY {fy}.")
            else:
                show_table(result.lots[cols])
        with tabs[1]:
            show_table(result.scheme_summary)
        with tabs[2]:
            show_table(result.open_lots)

        st.download_button("⬇️ Download Excel report", cg_excel_report(result, harvest),
                           f"MF_capital_gains_FY{fy}.xlsx", type="primary", width="stretch",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
footer()
