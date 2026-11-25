"""Mutual fund capital gains: FIFO lot matching, holding periods, grandfathering, tax estimate.

How the law works, in plain words:
  * FIFO: when you redeem units, the OLDEST units you bought are treated as sold first.
    So one redemption can be split across several purchase lots, each with its own
    purchase date, cost and holding period.
  * Equity-oriented funds: held more than 12 months = long term (LTCG), taxed at 12.5%
    on the year's total equity LTCG above Rs 1.25 lakh. Otherwise short term (STCG) at 20%.
  * Grandfathering: equity units bought on or before 31 Jan 2018 get a stepped-up cost:
    cost = higher of (actual cost) and (lower of: value on 31 Jan 2018, sale value).
    So gains made before Feb 2018 stay untaxed, but grandfathering can't create a loss.
  * Debt funds bought on/after 1 Apr 2023: always taxed at your slab rate.
    Bought earlier: long term after 24 months (12.5%), else slab rate.
  * Other funds (FoFs, international, gold...): long term after 24 months (12.5%), else slab.

All rates and dates come from config/tax_rules_2026_27.yaml.
"""

from __future__ import annotations

import io
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from taxdesk.rules import get_rule, load_rules
from taxdesk.sample_data import MF_COLUMNS
from taxdesk.tabular import _blank_mask, norm_header, parse_amounts, parse_dates

EQUITY, DEBT, OTHER = "equity", "debt", "other"
FUND_TYPES = (EQUITY, DEBT, OTHER)
EQ_ST, EQ_LT, LT_125, SLAB = "equity_stcg", "equity_ltcg", "ltcg_12_5", "slab"
TREATMENT_LABELS = {EQ_ST: "Equity STCG (20%)", EQ_LT: "Equity LTCG (12.5% above exemption)",
                    LT_125: "LTCG 12.5% (no exemption)", SLAB: "Slab rate (add to income)"}
UNIT_TOLERANCE = 0.0005

_COLUMN_SYNONYMS = {
    "date": ("date", "transaction date", "txn date", "trade date"),
    "scheme": ("scheme", "scheme name", "fund", "fund name"),
    "isin": ("isin", "isin code"),
    "fund_type": ("fund type", "type of fund", "category", "asset class"),
    "type": ("type", "transaction type", "txn type", "buy sell", "transaction"),
    "units": ("units", "quantity", "qty"),
    "nav": ("nav", "price", "nav per unit", "rate"),
    "amount": ("amount", "value", "amount rs", "transaction amount"),
}
_BUY_WORDS = ("buy", "purchase", "sip", "switch in", "switch-in", "switchin", "reinvest", "gift in",
              "systematic investment", "additional purchase", "new purchase")
_SELL_WORDS = ("sell", "sale", "redemption", "redeem", "switch out", "switch-out", "switchout", "swp",
               "gift out", "systematic withdrawal")


class TransactionsError(ValueError):
    """Raised when the transactions file is unusable (problems listed in plain words)."""


# =============================================================== loading ==========

def fy_label(day: date | pd.Timestamp) -> str:
    """Indian financial year of a date: 15-Aug-2026 -> '2026-27', 10-Mar-2026 -> '2025-26'."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def fy_bounds(fy: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """'2026-27' -> (1-Apr-2026, 31-Mar-2027)."""
    start = int(fy[:4])
    return pd.Timestamp(start, 4, 1), pd.Timestamp(start + 1, 3, 31)


def _map_columns(columns: list[str]) -> dict[str, str]:
    """Map our standard fields to the file's headers (case/punctuation insensitive)."""
    found: dict[str, str] = {}
    normalised = {norm_header(c): c for c in columns}
    for fname, names in _COLUMN_SYNONYMS.items():
        for n in names:
            if n in normalised and normalised[n] not in found.values():
                found[fname] = normalised[n]
                break
    return found


def _txn_type(text: object) -> str | None:
    """'Purchase - SIP' -> 'buy', 'Redemption' -> 'sell', anything else -> None."""
    t = str(text).strip().lower()
    if any(w in t for w in _SELL_WORDS):
        return "sell"
    if any(w in t for w in _BUY_WORDS):
        return "buy"
    return None


def _fund_type(text: object) -> str | None:
    """Normalise fund type text to equity / debt / other."""
    t = str(text).strip().lower()
    if t.startswith(("equity", "elss", "index", "large", "mid", "small", "flexi", "multi")):
        return EQUITY
    if t.startswith(("debt", "liquid", "gilt", "money market", "overnight", "short", "corporate bond")):
        return DEBT
    if t in {"", "nan", "none"}:
        return None
    return OTHER


@dataclass
class Transactions:
    """Clean transactions plus problems found."""

    data: pd.DataFrame          # date, scheme, isin, fund_type, type, units, nav, amount, key, source_row
    issues: pd.DataFrame


def clean_transactions(raw: pd.DataFrame) -> Transactions:
    """Validate a transactions table (template format). Bad rows are skipped and listed, never crash."""
    mapping = _map_columns(list(raw.columns))
    missing = [f for f in ("date", "scheme", "type", "units") if f not in mapping]
    if "nav" not in mapping and "amount" not in mapping:
        missing.append("nav or amount")
    if missing:
        raise TransactionsError(f"Missing column(s): {', '.join(missing)}. "
                                f"Expected columns: {', '.join(MF_COLUMNS)} (download the template).")
    first_row = int(raw.attrs.get("first_data_row", 2))
    df = pd.DataFrame({f: (raw[mapping[f]].astype(object) if f in mapping else None) for f in _COLUMN_SYNONYMS})
    df["source_row"] = np.arange(len(raw)) + first_row
    issues: list[dict[str, Any]] = []

    def flag(mask: pd.Series, problem: str) -> None:
        for idx in mask[mask].index:
            issues.append({"Row": int(df.at[idx, "source_row"]), "Problem": problem})

    blank = pd.concat([_blank_mask(df[f]) for f in mapping], axis=1).all(axis=1)
    df = df[~blank].copy()

    df["date"], bad_date = parse_dates(df["date"])
    df["units"], bad_units = parse_amounts(df["units"], decimals=4)
    df["nav"], bad_nav = parse_amounts(df["nav"], decimals=6)
    df["amount"], bad_amt = parse_amounts(df["amount"], decimals=2)
    df["units"] = df["units"].abs()
    df["amount"] = df["amount"].abs()
    df["type"] = df["type"].map(_txn_type)
    df["fund_type"] = df["fund_type"].map(_fund_type)
    df["scheme"] = df["scheme"].astype(object).where(~_blank_mask(df["scheme"]), "").astype(str).str.strip()
    df["isin"] = df["isin"].astype(object).where(~_blank_mask(df["isin"]), "").astype(str).str.strip().str.upper()

    # Fill NAV from amount / units, or amount from units x NAV, when one is missing.
    need_nav = (df["nav"] == 0) & (df["units"] > 0)
    df.loc[need_nav, "nav"] = (df.loc[need_nav, "amount"] / df.loc[need_nav, "units"]).round(6)
    need_amt = (df["amount"] == 0)
    df.loc[need_amt, "amount"] = (df.loc[need_amt, "units"] * df.loc[need_amt, "nav"]).round(2)

    problems = {
        "Date missing or not recognised": df["date"].isna() | bad_date,
        "Units missing, zero or not a number": (df["units"] <= 0) | bad_units,
        "Type must be buy or sell (or purchase/SIP/redemption)": df["type"].isna(),
        "Scheme name missing": df["scheme"] == "",
        "NAV/amount missing or not a number": (df["nav"] <= 0) | bad_nav | bad_amt,
    }
    bad = pd.Series(False, index=df.index)
    for problem, mask in problems.items():
        flag(mask & ~bad, f"{problem}; row skipped")
        bad |= mask
    no_type = df["fund_type"].isna() & ~bad
    flag(no_type, "Fund type missing; treated as 'other' (change it in the scheme table)")
    df.loc[no_type, "fund_type"] = OTHER
    df = df[~bad].copy()
    df["key"] = np.where(df["isin"] != "", df["isin"], df["scheme"])
    issues_df = pd.DataFrame(issues, columns=["Row", "Problem"]).sort_values("Row", kind="stable")
    cols = ["date", "scheme", "isin", "fund_type", "type", "units", "nav", "amount", "key", "source_row"]
    return Transactions(df[cols].reset_index(drop=True), issues_df.reset_index(drop=True))


def scheme_list(txns: Transactions) -> pd.DataFrame:
    """One row per scheme, for the editable 'fund type + 31-Jan-2018 NAV' table in the UI."""
    d = txns.data
    cutoff = pd.Timestamp(get_rule("capital_gains.equity.grandfathering.acquired_before"))
    g = d.groupby("key", sort=False).agg(scheme=("scheme", "first"), isin=("isin", "first"),
                                         fund_type=("fund_type", "first"), first_buy=("date", "min"))
    pre = d[(d["type"] == "buy") & (d["date"] < cutoff)].groupby("key").size()
    g["needs_fmv"] = g.index.map(lambda k: bool(pre.get(k, 0)))
    return g.reset_index()


# =============================================================== FIFO =============

def _is_long_term(buy: pd.Timestamp, sell: pd.Timestamp, months: int) -> bool:
    """Long term if held MORE than `months` months: sold after the same date `months` later."""
    return sell > buy + pd.DateOffset(months=months)


def classify(fund_type: str, buy: pd.Timestamp, sell: pd.Timestamp, rules: dict[str, Any]) -> tuple[str, str]:
    """Return (term 'Short'/'Long', tax treatment key) for one matched lot."""
    cg = rules["capital_gains"]
    if fund_type == EQUITY:
        lt = _is_long_term(buy, sell, cg["equity"]["long_term_after_months"])
        return ("Long", EQ_LT) if lt else ("Short", EQ_ST)
    if fund_type == DEBT and buy >= pd.Timestamp(cg["debt"]["specified_fund_from"]):
        return "Short", SLAB                       # specified MF: deemed short term
    months = cg[DEBT if fund_type == DEBT else OTHER]["long_term_after_months"]
    return ("Long", LT_125) if _is_long_term(buy, sell, months) else ("Short", SLAB)


@dataclass
class FifoResult:
    """Matched (realised) lots, remaining (open) lots and problems."""

    realised: pd.DataFrame
    open_lots: pd.DataFrame
    issues: list[str] = field(default_factory=list)


def fifo_match(txns: Transactions, fund_types: dict[str, str] | None = None,
               rules: dict[str, Any] | None = None) -> FifoResult:
    """Match every sell against the oldest remaining buy lots of the same scheme (FIFO).

    `fund_types` lets the user override a scheme's fund type (key -> equity/debt/other).
    """
    rules = rules or load_rules()
    fund_types = fund_types or {}
    d = txns.data.assign(_order=txns.data["type"].map({"buy": 0, "sell": 1}))
    d = d.sort_values(["key", "date", "_order"], kind="stable")
    realised: list[dict[str, Any]] = []
    open_rows: list[dict[str, Any]] = []
    issues: list[str] = []
    for key, g in d.groupby("key", sort=False):
        scheme, isin = g["scheme"].iat[0], g["isin"].iat[0]
        ftype = fund_types.get(key, g["fund_type"].iat[0])
        lots: deque[list[Any]] = deque()               # [buy_date, units_left, cost_per_unit]
        for t in g.itertuples(index=False):
            if t.type == "buy":
                lots.append([t.date, float(t.units), float(t.amount) / float(t.units)])
                continue
            to_sell = float(t.units)
            sale_per_unit = float(t.amount) / float(t.units)
            while to_sell > UNIT_TOLERANCE and lots:
                lot = lots[0]
                take = min(lot[1], to_sell)
                term, treatment = classify(ftype, lot[0], t.date, rules)
                realised.append({
                    "key": key, "Scheme": scheme, "ISIN": isin, "Fund Type": ftype,
                    "Buy Date": lot[0], "Sell Date": t.date, "Units": round(take, 4),
                    "Buy NAV": round(lot[2], 4), "Sell NAV": round(sale_per_unit, 4),
                    "Cost": round(take * lot[2], 2), "Sale Value": round(take * sale_per_unit, 2),
                    "Holding Days": int((t.date - lot[0]).days), "Term": term, "_treatment": treatment,
                    "FY": fy_label(t.date)})
                lot[1] -= take
                to_sell -= take
                if lot[1] <= UNIT_TOLERANCE:
                    lots.popleft()
            if to_sell > UNIT_TOLERANCE:
                issues.append(f"{scheme}: sale on {t.date:%d-%m-%Y} is {to_sell:,.3f} units more than held. "
                              "Earlier purchases are probably missing from the file; those units were ignored.")
        for lot in lots:
            open_rows.append({"key": key, "Scheme": scheme, "ISIN": isin, "Fund Type": ftype,
                              "Buy Date": lot[0], "Units": round(lot[1], 4), "Buy NAV": round(lot[2], 4),
                              "Cost": round(lot[1] * lot[2], 2)})
    realised_df = pd.DataFrame(realised, columns=[
        "key", "Scheme", "ISIN", "Fund Type", "Buy Date", "Sell Date", "Units", "Buy NAV", "Sell NAV", "Cost",
        "Sale Value", "Holding Days", "Term", "_treatment", "FY"])
    open_df = pd.DataFrame(open_rows, columns=["key", "Scheme", "ISIN", "Fund Type", "Buy Date", "Units",
                                               "Buy NAV", "Cost"])
    return FifoResult(realised_df, open_df, issues)


# =============================================================== tax ==============

def grandfathered_cost(actual_cost: float, fmv_value: float, sale_value: float) -> float:
    """Cost for equity bought on/before 31 Jan 2018: max(actual cost, min(FMV on 31 Jan 2018, sale value))."""
    return max(actual_cost, min(fmv_value, sale_value))


def apply_grandfathering(realised: pd.DataFrame, fmv_per_unit: dict[str, float],
                         rules: dict[str, Any] | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Add 'FMV 31-Jan-2018', 'Cost Used' and 'Gain' columns. Returns (table, warnings)."""
    rules = rules or load_rules()
    cutoff = pd.Timestamp(rules["capital_gains"]["equity"]["grandfathering"]["acquired_before"])
    df = realised.copy()
    eligible = (df["Fund Type"] == EQUITY) & (df["Buy Date"] < cutoff) & (df["_treatment"] == EQ_LT)
    fmv = df["key"].map(lambda k: fmv_per_unit.get(k)).astype(float)
    df["FMV 31-Jan-2018"] = np.where(eligible, fmv, np.nan)
    df["Cost Used"] = df["Cost"]
    has_fmv = eligible & fmv.notna() & (fmv > 0)
    df.loc[has_fmv, "Cost Used"] = [
        round(grandfathered_cost(c, f * u, s), 2) for c, f, u, s in
        zip(df.loc[has_fmv, "Cost"], fmv[has_fmv], df.loc[has_fmv, "Units"], df.loc[has_fmv, "Sale Value"])]
    df["Grandfathered"] = np.where(has_fmv, "Yes", np.where(eligible, "FMV missing", ""))
    df["Gain"] = (df["Sale Value"] - df["Cost Used"]).round(2)
    warnings = []
    missing = sorted(df.loc[eligible & ~has_fmv, "Scheme"].unique())
    if missing:
        warnings.append("31 Jan 2018 NAV not entered for: " + ", ".join(missing) +
                        ". Actual cost was used, so the gain may be overstated.")
    return df, warnings


@dataclass
class CapitalGainsResult:
    """Everything the MF page shows and exports for one financial year."""

    fy: str
    lots: pd.DataFrame                 # realised lots in this FY
    scheme_summary: pd.DataFrame
    totals: dict[str, float]
    open_lots: pd.DataFrame
    warnings: list[str]
    issues: pd.DataFrame


def _set_off(buckets: dict[str, float]) -> tuple[dict[str, float], float, list[str]]:
    """Set off capital losses (simplified, as the Act allows):
    short-term losses against any gains (other short-term first, then long-term);
    long-term losses only against long-term gains. Returns (net buckets, loss carried forward, notes)."""
    b = dict(buckets)
    notes: list[str] = []
    carried = 0.0

    def absorb(loss: float, targets: list[str]) -> float:
        for t in targets:
            if loss <= 0:
                break
            use = min(loss, max(b[t], 0.0))
            b[t] -= use
            loss -= use
        return loss

    for src, targets in ((EQ_ST, [SLAB, LT_125, EQ_LT]), (SLAB, [EQ_ST, LT_125, EQ_LT]),
                         (LT_125, [EQ_LT]), (EQ_LT, [LT_125])):
        if b[src] < 0:
            loss, b[src] = -b[src], 0.0
            notes.append(f"{TREATMENT_LABELS[src]} loss of Rs {loss:,.0f} set off against other gains.")
            carried += absorb(loss, targets)
    if carried > 0:
        notes.append(f"Unabsorbed capital loss of Rs {carried:,.0f} can be carried forward (file ITR on time).")
    return b, carried, notes


def compute_capital_gains(txns: Transactions, fy: str | None = None,
                          fund_types: dict[str, str] | None = None,
                          fmv_per_unit: dict[str, float] | None = None,
                          rules: dict[str, Any] | None = None) -> CapitalGainsResult:
    """FIFO + grandfathering + yearly totals and estimated tax for one financial year."""
    rules = rules or load_rules()
    fy = fy or rules["app_settings"]["default_financial_year"]
    eq = rules["capital_gains"]["equity"]
    fifo = fifo_match(txns, fund_types, rules)
    all_lots, gf_warnings = apply_grandfathering(fifo.realised, fmv_per_unit or {}, rules)
    lots = all_lots[all_lots["FY"] == fy].copy()
    lots["Tax Treatment"] = lots["_treatment"].map(TREATMENT_LABELS)

    gross = {k: float(lots.loc[lots["_treatment"] == k, "Gain"].sum()) for k in (EQ_ST, EQ_LT, LT_125, SLAB)}
    net, carried, notes = _set_off(gross)
    exemption = min(float(eq["ltcg_exemption"]), max(net[EQ_LT], 0.0))
    taxable_eq_lt = max(net[EQ_LT] - exemption, 0.0)
    tax = net[EQ_ST] * eq["stcg_rate"] + taxable_eq_lt * eq["ltcg_rate"] \
        + net[LT_125] * rules["capital_gains"]["other"]["ltcg_rate"]
    cess = tax * rules["income_tax"]["cess_rate"]
    totals = {
        "equity_stcg": round(gross[EQ_ST], 2), "equity_ltcg": round(gross[EQ_LT], 2),
        "ltcg_12_5_no_exemption": round(gross[LT_125], 2), "slab_rate_gains": round(gross[SLAB], 2),
        "equity_ltcg_after_set_off": round(net[EQ_LT], 2), "ltcg_exemption_used": round(exemption, 2),
        "taxable_equity_ltcg": round(taxable_eq_lt, 2),
        "tax_before_cess": round(tax, 2), "cess": round(cess, 2), "estimated_tax": round(tax + cess, 2),
        "loss_carried_forward": round(carried, 2),
        "harvest_room": round(float(eq["ltcg_exemption"]) - exemption, 2),   # unused tax-free LTCG
        "sale_value": round(float(lots["Sale Value"].sum()), 2), "cost_used": round(float(lots["Cost Used"].sum()), 2),
    }

    summary = _scheme_summary(lots)
    warnings = [*fifo.issues, *gf_warnings, *notes]
    if gross[SLAB]:
        warnings.append(f"Rs {gross[SLAB]:,.0f} of gains are taxed at the slab rate: add them to income "
                        "in the regime comparison. They are NOT included in the estimated tax here.")
    if fy != rules["app_settings"]["default_financial_year"]:
        warnings.append(f"Rates from the {rules['meta']['tax_year']} rules file were applied to {fy}. "
                        "Older years had different rates (e.g. 10%/15% before 23 Jul 2024).")
    open_lots = fifo.open_lots.drop(columns="key")
    return CapitalGainsResult(fy, lots.drop(columns=["_treatment"]), summary, totals, open_lots, warnings,
                              txns.issues)


def _scheme_summary(lots: pd.DataFrame) -> pd.DataFrame:
    """One row per scheme: units sold, sale value, cost and gains split by tax treatment."""
    cols = ["Scheme", "Fund Type", "Units Sold", "Sale Value", "Cost Used", "Equity STCG", "Equity LTCG",
            "LTCG 12.5% (no exemption)", "Slab-rate Gains", "Total Gain"]
    if lots.empty:
        return pd.DataFrame(columns=cols)
    t = lots.assign(**{
        "Equity STCG": np.where(lots["_treatment"] == EQ_ST, lots["Gain"], 0.0),
        "Equity LTCG": np.where(lots["_treatment"] == EQ_LT, lots["Gain"], 0.0),
        "LTCG 12.5% (no exemption)": np.where(lots["_treatment"] == LT_125, lots["Gain"], 0.0),
        "Slab-rate Gains": np.where(lots["_treatment"] == SLAB, lots["Gain"], 0.0)})
    out = t.groupby(["Scheme", "Fund Type"], sort=False).agg(**{
        "Units Sold": ("Units", "sum"), "Sale Value": ("Sale Value", "sum"), "Cost Used": ("Cost Used", "sum"),
        "Equity STCG": ("Equity STCG", "sum"), "Equity LTCG": ("Equity LTCG", "sum"),
        "LTCG 12.5% (no exemption)": ("LTCG 12.5% (no exemption)", "sum"),
        "Slab-rate Gains": ("Slab-rate Gains", "sum"), "Total Gain": ("Gain", "sum")}).reset_index()
    return out.round(2)[cols]


def harvest_plan(result: CapitalGainsResult, current_nav: dict[str, float], as_of: date | None = None,
                 fmv_per_unit: dict[str, float] | None = None,
                 rules: dict[str, Any] | None = None) -> pd.DataFrame:
    """For each equity scheme, how many units to redeem now to book up to the remaining
    tax-free LTCG (Rs 1.25 lakh minus LTCG already booked this year).

    Because redemptions are FIFO, only the oldest lots that are ALREADY long term can be used;
    we stop at the first lot that is still short term. Each row assumes that scheme alone is used.
    """
    rules = rules or load_rules()
    as_of = pd.Timestamp(as_of or date.today())
    room = result.totals["harvest_room"]
    months = rules["capital_gains"]["equity"]["long_term_after_months"]
    cutoff = pd.Timestamp(rules["capital_gains"]["equity"]["grandfathering"]["acquired_before"])
    fmv_per_unit = fmv_per_unit or {}
    rows = []
    lots = result.open_lots
    eq = lots[lots["Fund Type"] == EQUITY].copy()
    eq["key"] = np.where(eq["ISIN"] != "", eq["ISIN"], eq["Scheme"])
    for key, g in eq.sort_values("Buy Date").groupby("key", sort=False):
        nav = current_nav.get(key)
        if not nav:
            continue
        lt_units = lt_gain = units_needed = 0.0
        gain_so_far = 0.0
        for _, lot in g.iterrows():
            bought, units = lot["Buy Date"], float(lot["Units"])
            if not _is_long_term(bought, as_of, months):
                break                                   # FIFO: next units sold would be short term
            cost_pu = float(lot["Buy NAV"])
            if bought < cutoff and fmv_per_unit.get(key):
                cost_pu = max(cost_pu, min(fmv_per_unit[key], nav))
            gain_pu = nav - cost_pu
            lt_units += units
            lt_gain += units * gain_pu
            if gain_so_far < room and gain_pu > 0:
                need = min(units, (room - gain_so_far) / gain_pu)
                units_needed += need
                gain_so_far += need * gain_pu
            elif gain_so_far < room:
                units_needed += units                   # a loss-making older lot must be sold first (FIFO)
                gain_so_far += units * gain_pu
        rows.append({"Scheme": g["Scheme"].iat[0], "Current NAV": nav, "Long-term Units Available": round(lt_units, 3),
                     "Unrealised LTCG on Them": round(lt_gain, 2),
                     "Units to Redeem": round(units_needed, 3) if lt_gain > 0 else 0.0,
                     "Gain Booked": round(min(gain_so_far, room), 2) if lt_gain > 0 else 0.0,
                     "Redemption Value": round(units_needed * nav, 2) if lt_gain > 0 else 0.0})
    return pd.DataFrame(rows, columns=["Scheme", "Current NAV", "Long-term Units Available",
                                       "Unrealised LTCG on Them", "Units to Redeem", "Gain Booked",
                                       "Redemption Value"])


# =============================================================== CAS PDF ==========

def cas_available() -> bool:
    """True if the optional casparser library is installed."""
    try:
        import casparser  # noqa: F401
    except ImportError:
        return False
    return True


def cas_to_transactions(cas: dict[str, Any]) -> pd.DataFrame:
    """Convert casparser's dict output into our template columns.

    Units > 0 are treated as buys and units < 0 as sells; tax/stamp-duty/dividend-payout
    rows (no units) are skipped. The investor's PAN in the CAS is never copied.
    """
    rows = []
    for folio in cas.get("folios", []):
        for s in folio.get("schemes", []):
            stype = str(s.get("type") or "").upper()
            fund_type = EQUITY if stype == "EQUITY" else DEBT if stype == "DEBT" else OTHER
            for t in s.get("transactions", []):
                units = t.get("units")
                if units in (None, 0):
                    continue
                units = float(units)
                amount = abs(float(t.get("amount") or 0))
                rows.append({"Date": t.get("date"), "Scheme": s.get("scheme", ""), "ISIN": s.get("isin") or "",
                             "Fund Type": fund_type, "Type": "buy" if units > 0 else "sell",
                             "Units": abs(units), "NAV": float(t.get("nav") or 0), "Amount": amount})
    return pd.DataFrame(rows, columns=MF_COLUMNS)


def parse_cas_pdf(data: bytes, password: str) -> pd.DataFrame:
    """Read a CAMS/KFintech CAS PDF in memory. The password is used once and never stored."""
    try:
        import casparser
    except ImportError as exc:
        raise TransactionsError("CAS import needs the optional 'casparser' package.") from exc
    try:
        cas = casparser.read_cas_pdf(io.BytesIO(data), password, output="dict")
    except Exception as exc:  # noqa: BLE001 - casparser raises several types; show one friendly message
        raise TransactionsError("Could not read the CAS PDF. Check the password and that it is a "
                                "CAMS/KFintech detailed CAS.") from exc
    return cas_to_transactions(cas if isinstance(cas, dict) else dict(cas))
