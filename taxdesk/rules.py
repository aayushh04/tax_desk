"""Load the tax rules YAML file.

All rates, slabs, limits and dates live in config/tax_rules_2026_27.yaml.
Every other module asks this module for a value instead of hardcoding it, so a
change in the law means editing one YAML file, not hunting through code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RULES_PATH: Path = Path(__file__).resolve().parent.parent / "config" / "tax_rules_2026_27.yaml"


class RulesError(ValueError):
    """Raised when the rules file is missing, malformed, or a key is not found."""


def _validate_slabs(slabs: list[dict[str, Any]], name: str) -> None:
    """Check that slab limits go up, rates are between 0 and 1, and only the last slab is open-ended."""
    if not slabs:
        raise RulesError(f"{name}: slab list is empty")
    previous = 0
    for i, slab in enumerate(slabs):
        upto, rate = slab.get("upto"), slab.get("rate")
        if rate is None or not 0 <= float(rate) <= 1:
            raise RulesError(f"{name}: slab {i} has an invalid rate {rate!r}")
        is_last = i == len(slabs) - 1
        if upto is None:
            if not is_last:
                raise RulesError(f"{name}: only the last slab may have 'upto: null'")
            continue
        if upto <= previous:
            raise RulesError(f"{name}: slab limits must increase (slab {i})")
        previous = upto
    if slabs[-1].get("upto") is not None:
        raise RulesError(f"{name}: last slab must have 'upto: null' (no upper limit)")


def validate_rules(rules: dict[str, Any]) -> None:
    """Sanity-check the loaded rules so a typo in the YAML fails loudly at start-up."""
    for section in ("meta", "income_tax", "capital_gains", "gst", "app_settings"):
        if section not in rules:
            raise RulesError(f"rules file is missing the '{section}' section")
    _validate_slabs(rules["income_tax"]["new_regime"]["slabs"], "new_regime")
    _validate_slabs(rules["income_tax"]["old_regime"]["slabs"], "old_regime")
    cess = rules["income_tax"]["cess_rate"]
    if not 0 <= cess < 1:
        raise RulesError(f"cess_rate looks wrong: {cess}")


@lru_cache(maxsize=4)
def load_rules(path: str | Path = DEFAULT_RULES_PATH) -> dict[str, Any]:
    """Read, validate and cache the rules YAML. Returns a nested dict.

    The result is cached, so calling this many times only reads the file once.
    """
    path = Path(path)
    if not path.exists():
        raise RulesError(f"rules file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        rules = yaml.safe_load(fh)
    if not isinstance(rules, dict):
        raise RulesError("rules file did not contain a mapping at the top level")
    validate_rules(rules)
    return rules


def get_rule(dotted_key: str, rules: dict[str, Any] | None = None) -> Any:
    """Fetch one value by a dotted path, e.g. get_rule("income_tax.cess_rate") -> 0.04."""
    node: Any = rules if rules is not None else load_rules()
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise RulesError(f"rule not found: {dotted_key} (stopped at '{part}')")
        node = node[part]
    return node


def valid_gst_state_codes(rules: dict[str, Any] | None = None) -> set[str]:
    """Return the set of valid 2-digit GST state codes as strings, e.g. {'01', ..., '38', '97', '99'}."""
    spec = get_rule("gst.gstin.valid_state_codes", rules)
    low, high = spec["range"]
    codes = {f"{n:02d}" for n in range(low, high + 1)}
    codes.update(f"{n:02d}" for n in spec.get("extra", []))
    return codes
