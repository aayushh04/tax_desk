"""Shared Streamlit helpers for every page: page setup, footer, money format, table formatting.

This is the only module besides the pages that imports Streamlit. Tax logic stays in taxdesk/.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from taxdesk.formatting import format_inr
from taxdesk.rules import get_rule

_CSS = """
<style>
/* Tighter padding on phones so tables get the full width */
@media (max-width: 640px) {
  .block-container { padding-left: 0.8rem; padding-right: 0.8rem; padding-top: 2.5rem; }
  [data-testid="stMetricValue"] { font-size: 1.35rem; }
}
[data-testid="stMetric"] {
  border: 1px solid rgba(128,128,128,0.25); border-radius: 0.6rem; padding: 0.6rem 0.8rem;
}
.td-footer { font-size: 0.8rem; opacity: 0.75; text-align: center; padding: 0.5rem 0 1rem; }
</style>
"""


def setup_page(title: str, icon: str) -> None:
    """Call first on every page: sets the browser title/icon, wide layout and shared CSS."""
    st.set_page_config(page_title=f"{title} | TaxDesk", page_icon=icon, layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)


def footer() -> None:
    """The disclaimer footer required on every page."""
    st.divider()
    st.markdown(f"<div class='td-footer'>{get_rule('meta.disclaimer')}</div>", unsafe_allow_html=True)


def rupees(value: float, decimals: int = 0) -> str:
    """'₹12,34,568' in Indian grouping, for headline numbers."""
    return "₹" + format_inr(value, decimals)


def table_config(df: pd.DataFrame) -> dict[str, st.column_config.Column]:
    """Column formats for st.dataframe: amounts with separators, dates as DD-MM-YYYY."""
    config: dict[str, st.column_config.Column] = {}
    for col in df.columns:
        if col == "Similarity":
            config[col] = st.column_config.NumberColumn(col, format="%.1f")
        elif col.endswith(" Row") or col == "Row":
            config[col] = st.column_config.NumberColumn(col, format="%d", help="Row number in your file")
        elif pd.api.types.is_float_dtype(df[col]):
            config[col] = st.column_config.NumberColumn(col, format="localized")
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            config[col] = st.column_config.DateColumn(col, format="DD-MM-YYYY")
    return config


def show_table(df: pd.DataFrame, height: int | None = None) -> None:
    """A read-only, formatted, full-width table without the index column."""
    kwargs = {"height": height} if height else {}
    st.dataframe(df, hide_index=True, column_config=table_config(df), width="stretch", **kwargs)
