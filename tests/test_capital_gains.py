"""Capital gains tests with known answers (from the project brief), plus edge cases."""

from datetime import date

import pandas as pd
import pytest

from taxdesk.capital_gains import (DEBT, EQ_LT, EQ_ST, EQUITY, LT_125, OTHER, SLAB, TransactionsError,
                                   cas_to_transactions, classify, clean_transactions, compute_capital_gains,
                                   fifo_match, fy_label, grandfathered_cost, harvest_plan)
from taxdesk.rules import load_rules
from taxdesk.sample_data import generate_mf_sample


def _txns(rows: list[tuple]) -> pd.DataFrame:
    """Build a template-format table from (date, type, units, nav[, fund_type, scheme])."""
    out = []
    for r in rows:
        d, kind, units, nav = r[:4]
        out.append({"Date": d, "Scheme": r[5] if len(r) > 5 else "Test Fund", "ISIN": "",
                    "Fund Type": r[4] if len(r) > 4 else EQUITY, "Type": kind, "Units": units, "NAV": nav,
                    "Amount": units * nav})
    return pd.DataFrame(out)


def test_equity_ltcg_spec_example() -> None:
    """Invested 3 lakh, sold after 2 years for 5 lakh: LTCG 2 lakh, taxable 75,000, tax 9,375 + cess = 9,750."""
    t = clean_transactions(_txns([("2024-06-10", "buy", 10_000, 30), ("2026-06-11", "sell", 10_000, 50)]))
    r = compute_capital_gains(t, "2026-27")
    assert r.totals["equity_ltcg"] == 200_000
    assert r.totals["ltcg_exemption_used"] == 125_000
    assert r.totals["taxable_equity_ltcg"] == 75_000
    assert r.totals["tax_before_cess"] == 9_375
    assert r.totals["estimated_tax"] == 9_750


def test_fifo_spec_example() -> None:
    """Buy 100 @10 (Jan 2024), 100 @20 (Dec 2025), sell 150 @30 (Aug 2026): LTCG 2,000 on 100 units,
    STCG 500 on 50 units."""
    t = clean_transactions(_txns([("2024-01-15", "buy", 100, 10), ("2025-12-10", "buy", 100, 20),
                                  ("2026-08-20", "sell", 150, 30)]))
    r = compute_capital_gains(t, "2026-27")
    lots = r.lots
    assert len(lots) == 2
    lt, st = lots[lots["Term"] == "Long"].iloc[0], lots[lots["Term"] == "Short"].iloc[0]
    assert (lt["Units"], lt["Gain"]) == (100, 2_000)
    assert (st["Units"], st["Gain"]) == (50, 500)
    assert r.totals["equity_ltcg"] == 2_000 and r.totals["equity_stcg"] == 500
    assert r.totals["estimated_tax"] == pytest.approx(500 * 0.20 * 1.04)   # LTCG fully exempt
    assert r.open_lots["Units"].tolist() == [50]


def test_holding_period_boundary() -> None:
    rules = load_rules()
    buy = pd.Timestamp("2025-08-20")
    assert classify(EQUITY, buy, pd.Timestamp("2026-08-20"), rules) == ("Short", EQ_ST)   # exactly 12 months
    assert classify(EQUITY, buy, pd.Timestamp("2026-08-21"), rules) == ("Long", EQ_LT)


def test_debt_and_other_rules() -> None:
    rules = load_rules()
    sell = pd.Timestamp("2026-09-25")
    assert classify(DEBT, pd.Timestamp("2023-05-02"), sell, rules) == ("Short", SLAB)    # specified MF
    assert classify(DEBT, pd.Timestamp("2021-06-01"), sell, rules) == ("Long", LT_125)
    assert classify(DEBT, pd.Timestamp("2023-03-01"), pd.Timestamp("2024-06-01"), rules) == ("Short", SLAB)
    assert classify(OTHER, pd.Timestamp("2024-01-01"), sell, rules) == ("Long", LT_125)


@pytest.mark.parametrize("cost,fmv,sale,expected", [
    (100, 150, 200, 150),    # FMV between cost and sale: FMV is the cost
    (100, 250, 200, 200),    # FMV above sale: capped at sale value (no artificial loss)
    (100, 80, 200, 100),     # FMV below cost: actual cost stays
    (100, 150, 90, 100),     # sold at a loss: actual cost stays
])
def test_grandfathering_formula(cost, fmv, sale, expected) -> None:
    assert grandfathered_cost(cost, fmv, sale) == expected


def test_grandfathering_applied_to_pre_2018_lots() -> None:
    t = clean_transactions(_txns([("2017-05-01", "buy", 1_000, 20), ("2026-05-01", "sell", 1_000, 60)]))
    without = compute_capital_gains(t, "2026-27")
    with_fmv = compute_capital_gains(t, "2026-27", fmv_per_unit={"Test Fund": 35})
    assert without.totals["equity_ltcg"] == 40_000 and any("31 Jan 2018" in w for w in without.warnings)
    assert with_fmv.totals["equity_ltcg"] == 25_000       # 60,000 - 35,000
    assert with_fmv.lots["Grandfathered"].iat[0] == "Yes"


def test_set_off_short_term_loss_against_long_term_gain() -> None:
    t = clean_transactions(_txns([
        ("2026-01-10", "buy", 100, 100, EQUITY, "A"), ("2026-06-10", "sell", 100, 70, EQUITY, "A"),   # STCL 3,000
        ("2020-01-10", "buy", 1_000, 100, EQUITY, "B"), ("2026-06-10", "sell", 1_000, 300, EQUITY, "B"),  # LTCG 2 lakh
    ]))
    r = compute_capital_gains(t, "2026-27")
    assert r.totals["equity_stcg"] == -3_000
    assert r.totals["equity_ltcg_after_set_off"] == 197_000
    assert r.totals["taxable_equity_ltcg"] == 72_000


def test_fy_filter_and_labels() -> None:
    assert fy_label(date(2026, 8, 15)) == "2026-27" and fy_label(date(2027, 3, 31)) == "2026-27"
    assert fy_label(date(2026, 3, 31)) == "2025-26"
    t = clean_transactions(_txns([("2020-01-01", "buy", 10, 10), ("2023-01-01", "sell", 5, 20),
                                  ("2026-07-01", "sell", 5, 30)]))
    assert len(compute_capital_gains(t, "2026-27").lots) == 1
    assert len(compute_capital_gains(t, "2022-23").lots) == 1


def test_oversell_is_flagged_not_crashing() -> None:
    t = clean_transactions(_txns([("2024-01-01", "buy", 10, 10), ("2026-07-01", "sell", 15, 20)]))
    r = compute_capital_gains(t, "2026-27")
    assert r.lots["Units"].sum() == 10 and any("more than held" in w for w in r.warnings)


def test_messy_transactions() -> None:
    raw = pd.DataFrame({"date": ["01-04-2024", "", "bad", "05-05-2024"], "scheme name": ["X", "", "X", "X"],
                        "Fund Type": ["Equity", "", "equity", None], "Transaction Type": ["Purchase - SIP", "",
                        "buy", "Redemption"], "Units": ["1,000.5", "", "10", "500"], "NAV": ["10", "", "x", ""],
                        "Amount": ["", "", "", "6,000"]})
    t = clean_transactions(raw)
    assert len(t.data) == 2
    assert t.data["type"].tolist() == ["buy", "sell"]
    assert t.data["nav"].iat[1] == 12.0 and t.data["amount"].iat[0] == pytest.approx(10_005)
    problems = " ".join(t.issues["Problem"])
    assert "Date missing" in problems and "Fund type missing" in problems


def test_wrong_columns_message() -> None:
    with pytest.raises(TransactionsError, match="template"):
        clean_transactions(pd.DataFrame({"foo": [1]}))


def test_synthetic_history_fy_2026_27() -> None:
    mf = generate_mf_sample()
    t = clean_transactions(mf.transactions)
    r = compute_capital_gains(t, "2026-27", fmv_per_unit=mf.fmv_31jan2018)
    treatments = set(r.lots["Tax Treatment"])
    assert len(treatments) == 4                        # every tax treatment is exercised
    assert (r.lots["Grandfathered"] == "Yes").any()
    assert r.totals["estimated_tax"] > 0
    fifo = fifo_match(t)
    assert not fifo.issues                              # never sells more than held


def test_harvest_plan() -> None:
    t = clean_transactions(_txns([("2023-01-10", "buy", 1_000, 100), ("2026-10-01", "buy", 100, 150)]))
    r = compute_capital_gains(t, "2026-27")
    assert r.totals["harvest_room"] == 125_000
    plan = harvest_plan(r, {"Test Fund": 150.0}, as_of=date(2026, 11, 25))
    row = plan.iloc[0]
    assert row["Long-term Units Available"] == 1_000           # the Oct-2026 lot is still short term
    assert row["Unrealised LTCG on Them"] == 50_000
    assert row["Units to Redeem"] == 1_000 and row["Gain Booked"] == 50_000


def test_cas_conversion() -> None:
    cas = {"folios": [{"PAN": "ABCDE1234F", "schemes": [{
        "scheme": "Demo Equity Fund", "isin": "INF000000000", "type": "EQUITY", "transactions": [
            {"date": date(2024, 1, 5), "amount": 5000, "units": 100.0, "nav": 50, "type": "PURCHASE_SIP"},
            {"date": date(2024, 1, 5), "amount": 0.25, "units": None, "nav": None, "type": "STAMP_DUTY_TAX"},
            {"date": date(2026, 6, 5), "amount": -3000, "units": -40.0, "nav": 75, "type": "REDEMPTION"}]}]}]}
    df = cas_to_transactions(cas)
    assert df["Type"].tolist() == ["buy", "sell"] and df["Units"].tolist() == [100.0, 40.0]
    assert "ABCDE1234F" not in df.to_string()
    r = compute_capital_gains(clean_transactions(df), "2026-27")
    assert r.totals["equity_ltcg"] == pytest.approx(40 * 75 - 40 * 50)
