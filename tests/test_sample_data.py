"""Tests that the synthetic data contains exactly what we planted."""

import re
from datetime import date

import pandas as pd
from rapidfuzz import fuzz

from taxdesk.ids import is_valid_pan, validate_gstin
from taxdesk.sample_data import (N_INVOICES, N_SUPPLIERS, PLANTED, PROBABLE_MATCH,
                                 generate_gst_sample, generate_itr_clients, generate_mf_sample)


def _rough_normalise(no: str) -> str:
    """Uppercase, drop zero padding, keep letters/digits (the real normaliser arrives in Stage 1)."""
    no = re.sub(r"(?<![0-9])0+(?=[0-9])", "", no.upper())
    return re.sub(r"[^0-9A-Z]", "", no)


def test_same_seed_same_data() -> None:
    a, b = generate_gst_sample(7), generate_gst_sample(7)
    pd.testing.assert_frame_equal(a.gstr2b, b.gstr2b)


def test_gst_sizes_and_planted_counts() -> None:
    s = generate_gst_sample()
    assert len(s.suppliers) == N_SUPPLIERS
    assert len(s.purchase_register) == N_INVOICES
    for category, n in PLANTED.items():
        assert s.expected_counts[category] == n
    assert len(s.gstr2b) == N_INVOICES - PLANTED["in_books_not_in_2b"] + PLANTED["in_2b_not_in_books"]


def test_all_supplier_gstins_valid_and_unique() -> None:
    s = generate_gst_sample()
    assert s.suppliers["Supplier GSTIN"].is_unique
    assert all(validate_gstin(g).valid for g in s.suppliers["Supplier GSTIN"])
    assert validate_gstin(s.client_gstin).valid


def test_missing_invoices_spread_over_several_suppliers() -> None:
    key = generate_gst_sample().answer_key
    assert key.loc[key.expected_category == "in_books_not_in_2b", "Supplier GSTIN"].nunique() >= 3


def test_typos_are_close_but_not_equal() -> None:
    key = generate_gst_sample().answer_key
    for _, row in key[key.expected_category == PROBABLE_MATCH].iterrows():
        a, b = _rough_normalise(row["Books Invoice No"]), _rough_normalise(row["2B Invoice No"])
        assert a != b
        assert fuzz.ratio(a, b) >= 90


def test_amount_differences_exceed_tolerance_and_rounding_does_not() -> None:
    s = generate_gst_sample()
    books = s.purchase_register.set_index(["Supplier GSTIN", "Invoice No"])
    for _, row in s.answer_key.iterrows():
        if row.expected_category not in {"matched", "amount_difference"}:
            continue
        b = books.loc[(row["Supplier GSTIN"], row["Books Invoice No"])]
        g = s.gstr2b[(s.gstr2b["Supplier GSTIN"] == row["Supplier GSTIN"])
                     & (s.gstr2b["Invoice No"] == row["2B Invoice No"])].iloc[0]
        worst = max(abs(b[h] - g[h]) for h in ("IGST", "CGST", "SGST"))
        if row.expected_category == "amount_difference":
            assert worst > 1
        else:
            assert worst <= 0.5


def test_itr_clients() -> None:
    clients = generate_itr_clients()
    assert len(clients) == 3
    assert all(is_valid_pan(p) for p in clients["pan"])


def test_mf_history_is_consistent() -> None:
    mf = generate_mf_sample()
    t = mf.transactions
    assert t["Date"].min().year == 2016 and t["Date"].max().year == 2026
    assert {"equity", "debt", "other"} <= set(t["Fund Type"])
    assert (t["Type"] == "buy").sum() > 100                       # SIPs
    for _, g in t.groupby("ISIN"):                                # never sell more than held
        held = 0.0
        for _, r in g.iterrows():
            held += r["Units"] if r["Type"] == "buy" else -r["Units"]
            assert held >= -0.001
    fy_sales = t[(t["Type"] == "sell") & (t["Date"] >= pd.Timestamp(date(2026, 4, 1)))]
    assert len(fy_sales) >= 4
    pre_2018 = t[(t["Fund Type"] == "equity") & (t["Date"] < pd.Timestamp(date(2018, 2, 1)))]
    assert set(pre_2018["ISIN"]) == set(mf.fmv_31jan2018)
