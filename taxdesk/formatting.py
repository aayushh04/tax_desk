"""Display helpers shared by all modules (pure Python, no Streamlit)."""

from __future__ import annotations

import math
import re


def format_inr(value: float | int | None, decimals: int = 2, symbol: bool = False) -> str:
    """Format a number the Indian way: 1234567.5 -> '12,34,567.50' (lakh/crore grouping).

    Indian grouping puts the first comma after 3 digits from the right, then every 2 digits.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    negative = value < 0
    whole, _, frac = f"{abs(value):.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = f"{head},{tail}"
    text = whole + (f".{frac}" if decimals else "")
    if symbol:
        text = "Rs " + text
    return ("-" if negative else "") + text
