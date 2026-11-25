"""ITR regime tests with known answers (from the project brief), plus edge cases."""

import pytest

from taxdesk.itr import (NEW, OLD, IncomeInputs, compare_regimes, compute_regime, inputs_from_row,
                         round_to, slab_tax)
from taxdesk.rules import get_rule
from taxdesk.sample_data import generate_itr_clients


def test_new_regime_12_75_lakh_salary_pays_nothing() -> None:
    r = compute_regime(IncomeInputs(gross_salary=1_275_000), NEW)
    assert r.taxable_income == 1_200_000
    assert r.slab_tax == 60_000
    assert r.rebate == 60_000
    assert r.total_tax == 0


def test_new_regime_13_lakh_marginal_relief() -> None:
    r = compute_regime(IncomeInputs(gross_salary=1_300_000), NEW)
    assert r.taxable_income == 1_225_000
    assert r.slab_tax == 63_750
    assert r.tax_after_rebate == 25_000           # capped at income above Rs 12 lakh
    assert r.marginal_relief == 38_750
    assert r.total_tax == 26_000                  # plus 4% cess


def test_old_regime_10_lakh_taxable() -> None:
    r = compute_regime(IncomeInputs(gross_salary=1_050_000), OLD)
    assert r.taxable_income == 1_000_000
    assert r.slab_tax == 112_500
    assert r.total_tax == 117_000


def test_marginal_relief_ends_where_normal_tax_is_lower() -> None:
    """Relief applies only while slab tax exceeds the income above Rs 12 lakh (~Rs 12.70 lakh)."""
    r = compute_regime(IncomeInputs(gross_salary=1_275_000 + 80_000), NEW)   # taxable 12.8 lakh
    assert r.marginal_relief == 0
    assert r.tax_after_rebate == r.slab_tax == 72_000


def test_old_regime_rebate_up_to_5_lakh() -> None:
    r = compute_regime(IncomeInputs(gross_salary=550_000), OLD)
    assert r.taxable_income == 500_000 and r.slab_tax == 12_500 and r.total_tax == 0


def test_deductions_are_capped_and_old_regime_only() -> None:
    inp = IncomeInputs(gross_salary=2_000_000, sec_123_80c=300_000, sec_126_80d=200_000,
                       home_loan_interest=350_000, hra_exemption=100_000)
    old = compute_regime(inp, OLD)
    assert old.deduction_123 == get_rule("income_tax.deductions.sec_123.limit")
    assert old.deduction_126 == get_rule("income_tax.deductions.sec_126.limit_total_max")
    assert old.income_from_house_property == -200_000
    new = compute_regime(inp, NEW)
    assert new.total_deductions == 0 and new.hra_exemption == 0 and new.income_from_house_property == 0
    assert any("not allowed" in n for n in new.notes)


def test_let_out_property_30_percent() -> None:
    r = compute_regime(IncomeInputs(rent_received=240_000, municipal_tax_paid=12_000), NEW)
    assert r.income_from_house_property == pytest.approx(228_000 * 0.7)


def test_comparison_and_sample_clients() -> None:
    clients = generate_itr_clients().set_index("client_id")
    c1 = compare_regimes(inputs_from_row(clients.loc["C001"]))
    assert c1.cheaper == NEW and c1.new.marginal_relief > 0
    c2 = compare_regimes(inputs_from_row(clients.loc["C002"]))
    assert c2.cheaper == OLD and c2.saving > 0
    assert c2.saving == abs(c2.new.total_tax - c2.old.total_tax)


def test_warnings_and_validation() -> None:
    assert any("surcharge" in w for w in compare_regimes(IncomeInputs(gross_salary=6_000_000)).warnings)
    assert any("Senior" in w for w in compare_regimes(IncomeInputs(gross_salary=900_000, age=65)).warnings)
    with pytest.raises(ValueError, match="negative"):
        compare_regimes(IncomeInputs(gross_salary=-1))


def test_zero_income() -> None:
    cmp = compare_regimes(IncomeInputs())
    assert cmp.new.total_tax == cmp.old.total_tax == 0 and cmp.cheaper == "equal"


def test_helpers() -> None:
    assert round_to(12_345, 10) == 12_350 and round_to(12_344, 10) == 12_340
    tax, lines = slab_tax(900_000, get_rule("income_tax.new_regime.slabs"))
    assert tax == 20_000 + 10_000 and len(lines) == 3
