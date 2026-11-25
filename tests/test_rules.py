"""Tests for the rules YAML loader."""

import copy

import pytest

from taxdesk.rules import RulesError, get_rule, load_rules, valid_gst_state_codes, validate_rules


def test_rules_load_and_key_values() -> None:
    assert get_rule("meta.tax_year") == "2026-27"
    assert get_rule("income_tax.cess_rate") == 0.04
    assert get_rule("income_tax.new_regime.standard_deduction") == 75000
    assert get_rule("income_tax.new_regime.rebate.max_rebate") == 60000
    assert get_rule("income_tax.new_regime.rebate.income_limit") == 1200000
    assert get_rule("income_tax.deductions.sec_123.limit") == 150000
    assert get_rule("capital_gains.equity.ltcg_exemption") == 125000


def test_slabs_end_open_ended() -> None:
    for regime in ("new_regime", "old_regime"):
        assert get_rule(f"income_tax.{regime}.slabs")[-1]["upto"] is None


def test_missing_key_gives_clear_error() -> None:
    with pytest.raises(RulesError, match="not found"):
        get_rule("income_tax.no_such_key")


def test_validation_rejects_bad_slabs() -> None:
    broken = copy.deepcopy(load_rules())
    broken["income_tax"]["new_regime"]["slabs"][2]["upto"] = 100  # goes down
    with pytest.raises(RulesError):
        validate_rules(broken)


def test_state_codes() -> None:
    codes = valid_gst_state_codes()
    assert {"01", "27", "38", "97", "99"} <= codes
    assert "00" not in codes and "39" not in codes
