"""Income tax computation for a resident salaried individual: new regime vs old regime.

The flow mirrors how a CA writes a computation of income:

    Income from salary          gross salary - HRA exemption (old only) - standard deduction
  + Income from house property  let-out rent - municipal tax - 30%, minus home-loan
                                interest on a self-occupied house (old only, max Rs 2 lakh)
  + Income from other sources   savings + FD interest
  = Gross total income
  - Deductions (old only)       Section 123 (formerly 80C), Section 126 (formerly 80D)
  = Total (taxable) income      rounded to the nearest Rs 10
    Tax on slabs
  - Rebate (s.156, formerly 87A) or marginal relief just above the rebate limit
  + Health & education cess 4%
  = Tax payable                 rounded to the nearest Rs 10

Every number comes from config/tax_rules_2026_27.yaml.
Out of scope (warned, not computed): surcharge (> Rs 50 lakh), senior-citizen slabs, business income.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pandas as pd

from taxdesk.rules import get_rule, load_rules

NEW = "new"
OLD = "old"
REGIME_LABELS = {NEW: "New regime", OLD: "Old regime"}


@dataclass
class IncomeInputs:
    """Everything the user enters for one client, in rupees per year."""

    gross_salary: float = 0.0
    savings_interest: float = 0.0
    fd_interest: float = 0.0
    rent_received: float = 0.0
    municipal_tax_paid: float = 0.0
    sec_123_80c: float = 0.0
    sec_126_80d: float = 0.0
    home_loan_interest: float = 0.0
    hra_exemption: float = 0.0
    age: int = 30

    def validate(self) -> list[str]:
        """Plain-English problems with the inputs (empty list = fine)."""
        problems = []
        for name, value in asdict(self).items():
            if value is None or value < 0:
                problems.append(f"{name.replace('_', ' ').capitalize()} cannot be negative.")
        if self.municipal_tax_paid > self.rent_received:
            problems.append("Municipal tax paid is more than the rent received.")
        if self.hra_exemption > self.gross_salary:
            problems.append("HRA exemption cannot be more than the gross salary.")
        return problems


@dataclass
class SlabLine:
    """Tax on one slab: e.g. 'Rs 4,00,001 to Rs 8,00,000 at 5% on Rs 4,00,000 = Rs 20,000'."""

    lower: float
    upper: float | None
    rate: float
    income_in_slab: float
    tax: float


@dataclass
class RegimeResult:
    """A full step-by-step computation under one regime."""

    regime: str
    gross_salary: float
    hra_exemption: float
    standard_deduction: float
    income_from_salary: float
    income_from_house_property: float
    income_from_other_sources: float
    gross_total_income: float
    deduction_123: float
    deduction_126: float
    total_deductions: float
    taxable_income: float
    slab_tax: float
    rebate: float
    marginal_relief: float
    tax_after_rebate: float
    cess: float
    total_tax: float
    slabs: list[SlabLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Comparison:
    """Both regimes plus which one is cheaper."""

    new: RegimeResult
    old: RegimeResult
    cheaper: str               # "new", "old" or "equal"
    saving: float
    warnings: list[str] = field(default_factory=list)


def round_to(value: float, nearest: int) -> float:
    """Round to the nearest multiple (5 rounds up): round_to(12345, 10) -> 12350."""
    if nearest <= 1:
        return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    units = Decimal(str(value)) / Decimal(nearest)
    return float(units.quantize(Decimal("1"), rounding=ROUND_HALF_UP) * nearest)


def slab_tax(income: float, slabs: list[dict[str, Any]]) -> tuple[float, list[SlabLine]]:
    """Tax on `income` using progressive slabs. Each slab's rate applies only to the part inside it."""
    total = 0.0
    lines: list[SlabLine] = []
    lower = 0.0
    for slab in slabs:
        upper = slab["upto"]
        rate = float(slab["rate"])
        top = income if upper is None else min(income, float(upper))
        in_slab = max(0.0, top - lower)
        tax = in_slab * rate
        lines.append(SlabLine(lower, None if upper is None else float(upper), rate, in_slab, round(tax, 2)))
        total += tax
        if upper is None or income <= upper:
            break
        lower = float(upper)
    return round(total, 2), lines


def _house_property(inputs: IncomeInputs, regime: str, rules: dict[str, Any]) -> tuple[float, list[str]]:
    """Income from house property. Let-out: (rent - municipal tax) less 30% standard deduction.
    Self-occupied home-loan interest is allowed only in the old regime, up to the limit."""
    notes: list[str] = []
    rate = get_rule("income_tax.house_property.standard_deduction_rate", rules)
    nav = max(0.0, inputs.rent_received - inputs.municipal_tax_paid)
    income = nav - nav * rate
    if inputs.home_loan_interest:
        if regime == OLD:
            limit = get_rule("income_tax.deductions.home_loan_interest.limit", rules)
            allowed = min(inputs.home_loan_interest, limit)
            if allowed < inputs.home_loan_interest:
                notes.append(f"Home-loan interest capped at Rs {limit:,.0f}.")
            income -= allowed
        else:
            notes.append("Home-loan interest on a self-occupied house is not allowed in the new regime.")
    return round(income, 2), notes


def compute_regime(inputs: IncomeInputs, regime: str, rules: dict[str, Any] | None = None) -> RegimeResult:
    """Compute tax under one regime ('new' or 'old'), keeping every intermediate step."""
    rules = rules or load_rules()
    it = rules["income_tax"]
    reg = it["new_regime" if regime == NEW else "old_regime"]
    notes: list[str] = []

    hra = inputs.hra_exemption if regime == OLD else 0.0
    if regime == NEW and inputs.hra_exemption:
        notes.append("HRA exemption is not available in the new regime.")
    after_hra = max(0.0, inputs.gross_salary - hra)
    std = min(float(reg["standard_deduction"]), after_hra)
    salary = after_hra - std

    house, house_notes = _house_property(inputs, regime, rules)
    notes += house_notes
    other = inputs.savings_interest + inputs.fd_interest
    gti = max(0.0, salary + house + other)     # a house-property loss reduces other income

    d123 = d126 = 0.0
    if regime == OLD:
        ded = it["deductions"]
        d123 = min(inputs.sec_123_80c, ded["sec_123"]["limit"])
        d126 = min(inputs.sec_126_80d, ded["sec_126"]["limit_total_max"])
        if d123 < inputs.sec_123_80c:
            notes.append(f"{ded['sec_123']['label']} capped at Rs {ded['sec_123']['limit']:,.0f}.")
        if d126 < inputs.sec_126_80d:
            notes.append(f"{ded['sec_126']['label']} capped at Rs {ded['sec_126']['limit_total_max']:,.0f}.")
    elif inputs.sec_123_80c or inputs.sec_126_80d:
        notes.append("Sections 123 and 126 (formerly 80C/80D) are not allowed in the new regime.")
    total_ded = min(d123 + d126, gti)

    taxable = round_to(gti - total_ded, it["rounding"]["income_to_nearest"])
    tax, lines = slab_tax(taxable, reg["slabs"])

    rebate_rule = reg["rebate"]
    rebate = relief = 0.0
    if taxable <= rebate_rule["income_limit"]:
        rebate = min(tax, float(rebate_rule["max_rebate"]))
    elif rebate_rule.get("marginal_relief"):
        excess = taxable - rebate_rule["income_limit"]
        if tax > excess:                         # tax may not exceed the income above the limit
            relief = round(tax - excess, 2)
    after = round(tax - rebate - relief, 2)
    cess = round(after * it["cess_rate"], 2)
    total = round_to(after + cess, it["rounding"]["tax_to_nearest"])

    return RegimeResult(regime, inputs.gross_salary, hra, std, round(salary, 2), house, round(other, 2),
                        round(gti, 2), d123, d126, round(total_ded, 2), taxable, tax, rebate, relief, after,
                        cess, total, lines, notes)


def compare_regimes(inputs: IncomeInputs, rules: dict[str, Any] | None = None) -> Comparison:
    """Compute both regimes and say which is cheaper and by how much."""
    rules = rules or load_rules()
    problems = inputs.validate()
    if problems:
        raise ValueError(" ".join(problems))
    new, old = compute_regime(inputs, NEW, rules), compute_regime(inputs, OLD, rules)
    warnings: list[str] = []
    limit = get_rule("income_tax.surcharge_warning_above", rules)
    if max(new.gross_total_income, old.gross_total_income) > limit:
        warnings.append(f"Income is above Rs {limit:,.0f}: surcharge applies and is NOT included here.")
    if inputs.age >= get_rule("income_tax.senior_citizen_age", rules):
        warnings.append("Senior-citizen slabs (old regime) are not modelled. Old-regime figures will be too high.")
    if new.total_tax == old.total_tax:
        cheaper, saving = "equal", 0.0
    else:
        cheaper = NEW if new.total_tax < old.total_tax else OLD
        saving = abs(new.total_tax - old.total_tax)
    return Comparison(new, old, cheaper, saving, warnings)


def comparison_table(cmp: Comparison, rules: dict[str, Any] | None = None) -> pd.DataFrame:
    """Side-by-side step table: one row per computation step, one column per regime."""
    rules = rules or load_rules()
    ded = rules["income_tax"]["deductions"]
    reb = rules["income_tax"]["new_regime"]["rebate"]
    cess_pct = rules["income_tax"]["cess_rate"] * 100
    steps = [
        ("Gross salary", "gross_salary"),
        ("Less: HRA exemption", "hra_exemption"),
        ("Less: Standard deduction", "standard_deduction"),
        ("Income from salary", "income_from_salary"),
        ("Income from house property", "income_from_house_property"),
        ("Income from other sources (interest)", "income_from_other_sources"),
        ("Gross total income", "gross_total_income"),
        (f"Less: {ded['sec_123']['label']}", "deduction_123"),
        (f"Less: {ded['sec_126']['label']}", "deduction_126"),
        ("Taxable income (rounded to Rs 10)", "taxable_income"),
        ("Tax on slabs", "slab_tax"),
        (f"Less: Rebate u/s {reb['section_new']} (formerly {reb['section_old']})", "rebate"),
        ("Less: Marginal relief", "marginal_relief"),
        ("Tax after rebate", "tax_after_rebate"),
        (f"Add: Health & education cess {cess_pct:g}%", "cess"),
        ("Total tax payable", "total_tax"),
    ]
    return pd.DataFrame({
        "Step": [label for label, _ in steps],
        REGIME_LABELS[NEW]: [float(getattr(cmp.new, attr)) for _, attr in steps],
        REGIME_LABELS[OLD]: [float(getattr(cmp.old, attr)) for _, attr in steps],
    })


def slab_table(result: RegimeResult) -> pd.DataFrame:
    """The slab-by-slab working for one regime."""
    rows = []
    for s in result.slabs:
        band = f"Above Rs {s.lower:,.0f}" if s.upper is None else f"Rs {s.lower:,.0f} to Rs {s.upper:,.0f}"
        rows.append({"Slab": band, "Rate": f"{s.rate:.0%}", "Income in slab": s.income_in_slab, "Tax": s.tax})
    return pd.DataFrame(rows, columns=["Slab", "Rate", "Income in slab", "Tax"])


def inputs_from_row(row: dict[str, Any] | pd.Series) -> IncomeInputs:
    """Build IncomeInputs from a sample-client row (extra keys such as name/PAN are ignored)."""
    names = IncomeInputs.__dataclass_fields__.keys()
    return IncomeInputs(**{k: (int(row[k]) if k == "age" else float(row[k])) for k in names if k in row})
