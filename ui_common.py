"""Shared Streamlit helpers: page setup, statements with note references, callouts, tables.

Visual world: Notes to Accounts. Each module opens on a statement (Particulars, Note, Amount)
like an annual report's financial statement; every note number links to a numbered note
further down the page that holds the working. Navy binding, white statement sheets on a
cool grey ground, ochre note references, red only where money is at risk.
This is the only module besides the pages that imports Streamlit; tax logic stays in taxdesk/.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from html import escape
from urllib.parse import quote

import pandas as pd
import streamlit as st

from taxdesk.formatting import format_inr
from taxdesk.rules import get_rule

NAVY, GROUND, RULE, HAIR, MUTED = "#14213D", "#F3F5F8", "#D5DBE5", "#E6EAF0", "#5A6782"
OCHRE, OCHRE_TEXT, RISK, AGREED = "#C98A12", "#8F5E06", "#B42318", "#1F7A4D"

# Tones used by chips, callouts, table status words and alerts: (text colour, border colour, tint).
TONES: dict[str, tuple[str, str, str]] = {
    "agreed": (AGREED, "#9CCBB2", "#EEF7F2"),
    "review": (OCHRE_TEXT, OCHRE, "#FBF4E6"),
    "risk": (RISK, "#E7A9A3", "#FCEFEE"),
    "neutral": (NAVY, RULE, "#FFFFFF"),
}

# Alert icons, authored in one 1.8px stroke so they match each other.
_ICONS = {
    "Info": ("neutral", '<circle cx="12" cy="12" r="8.6"/><path d="M12 11v5.4"/><path d="M12 7.6v.1"/>'),
    "Success": ("agreed", '<circle cx="12" cy="12" r="8.6"/><path d="M8.2 12.3l2.6 2.6 5-5.4"/>'),
    "Warning": ("review", '<path d="M12 4.2l8.4 14.6H3.6z"/><path d="M12 10v4.2"/><path d="M12 16.6v.1"/>'),
    "Error": ("risk", '<circle cx="12" cy="12" r="8.6"/><path d="M9.2 9.2l5.6 5.6"/><path d="M14.8 9.2l-5.6 5.6"/>'),
}


def _icon_uri(kind: str) -> str:
    """An alert icon as a CSS data URI."""
    tone, paths = _ICONS[kind]
    color = TONES[tone][0]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
    return f'url("data:image/svg+xml,{quote(svg)}")'


_ALERT_CSS = "".join(
    f'[data-testid="stAlertContainer"]:has([data-testid="stAlertContent{kind}"]) '
    f'{{ border-color:{TONES[tone][1]}; background-color:{TONES[tone][2]} !important; '
    f'background-image:{_icon_uri(kind)}; }}\n'
    for kind, (tone, _) in _ICONS.items())

_CSS = f"""
<style>
:root {{ --navy:{NAVY}; --ground:{GROUND}; --rule:{RULE}; --hair:{HAIR}; --muted:{MUTED};
        --ochre:{OCHRE}; --ochre-text:{OCHRE_TEXT}; --risk:{RISK}; --agreed:{AGREED};
        --serif:'Source Serif 4', Georgia, serif; }}
html, body, [data-testid="stAppViewContainer"] {{ font-variant-numeric: tabular-nums; }}
::selection {{ background:#F5E3BC; color:var(--navy); }}
* {{ caret-color: var(--navy); scrollbar-color: #B8C2D3 transparent; }}
:focus-visible {{ outline:2px solid var(--navy) !important; outline-offset:2px; }}
a {{ text-underline-offset:3px; }}
.block-container {{ padding-top:2.4rem; max-width:1240px; }}

/* Navy binding */
[data-testid="stSidebarNav"] a {{ border-radius:2px; padding:.5rem .8rem; margin-bottom:2px; }}
[data-testid="stSidebarNav"] a span {{ color:#C9D2E3; font-size:.95rem; }}
[data-testid="stSidebarNav"] a:hover {{ background:#1E2E52; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background:#23365F; }}
[data-testid="stSidebarNav"] a[aria-current="page"] span {{ color:#fff; font-weight:600; }}
/* Brand first, then the nav: Streamlit draws the nav before page content, so reorder the column */
[data-testid="stSidebarContent"] {{ display:flex; flex-direction:column; }}
[data-testid="stSidebarHeader"] {{ order:0; height:auto; min-height:2.6rem; }}
[data-testid="stSidebarUserContent"] {{ order:1; padding-top:0 !important; padding-bottom:1rem !important; }}
[data-testid="stSidebarNav"] {{ order:2; }}
[data-testid="stSidebarNavSeparator"] {{ display:none; }}
.td-side {{ color:#AEB9CF; font-size:.85rem; line-height:1.55; border-bottom:1px solid #2A3B62; padding-bottom:1.1rem; }}
.td-side b {{ font:700 1.5rem var(--serif); color:#fff; display:block; margin-bottom:.2rem; }}

/* Page header: title and subtitle left, client and period right */
.td-head {{ display:flex; justify-content:space-between; align-items:flex-end; gap:2rem;
  border-bottom:1px solid var(--rule); padding-bottom:.9rem; margin-bottom:1.4rem; }}
.td-head h1 {{ font:700 2.25rem/1.15 var(--serif); margin:0; padding:0; letter-spacing:-.01em; color:var(--navy); }}
.td-head p {{ color:var(--muted); margin:.35rem 0 0; font-size:1rem; }}
.td-meta {{ color:var(--muted); font-size:.95rem; text-align:right; white-space:nowrap; }}
.td-meta b {{ display:block; color:var(--navy); font-weight:600; }}

/* Statement: Particulars, Note, amounts */
.td-stmt {{ background:#fff; border:1px solid var(--rule); padding:1.25rem 1.5rem 1.1rem; margin-bottom:1rem; }}
.td-stmt h2 {{ font:600 1.3rem var(--serif); margin:0 0 .8rem; padding:0; color:var(--navy); }}
.td-stmt table {{ width:100%; border-collapse:collapse; font-size:.97rem; }}
.td-stmt th {{ font-size:.74rem; font-weight:600; letter-spacing:.08em; text-transform:uppercase; color:var(--muted);
  text-align:right; padding:.5rem .45rem; border-bottom:1px solid var(--navy); white-space:nowrap; }}
.td-stmt th:first-child, .td-stmt td:first-child {{ text-align:left; padding-left:0; }}
.td-stmt td {{ padding:.62rem .45rem; border-bottom:1px solid var(--hair); text-align:right; color:var(--navy); }}
.td-stmt table, .td-stmt th, .td-stmt td {{ border-left:0 !important; border-right:0 !important; }}
.td-stmt table {{ border:0 !important; margin:0; }}
.td-stmt th {{ background:transparent !important; border-top:0 !important; }}
.td-stmt td {{ border-top:0; line-height:1.4; }}
.td-stmt td.amt {{ white-space:nowrap; }}
.td-stmt td.ref {{ white-space:nowrap; }}
.td-stmt tr.total td.amt.pick {{ color:var(--agreed); }}
.td-stmt th.pick {{ color:var(--agreed); }}
.td-stmt td.ref {{ text-align:center; width:3.6rem; }}
.td-stmt td.ref a {{ color:var(--ochre-text); font-weight:700; text-decoration:none; padding:.1rem .3rem; }}
.td-stmt td.ref a:hover {{ text-decoration:underline; }}
.td-stmt tr.sub td {{ border-top:1px solid var(--navy); font-weight:600; }}
.td-stmt tr.total td {{ border-top:1px solid var(--navy); border-bottom:3px double var(--navy); font-weight:700; }}
.td-stmt tr.risk td.amt {{ color:var(--risk); font-weight:700; }}
.td-stmt tr.risk td:first-child {{ color:var(--risk); font-weight:600; }}
.td-stmt tr.memo td {{ color:var(--muted); }}
.td-stmt tr.memo td.amt {{ color:var(--muted); }}

/* Callout: the one figure the statement exists to show */
.td-call {{ background:#fff; border:1px solid var(--rule); padding:1.2rem 1.4rem 1.3rem; margin-bottom:.9rem; }}
.td-call .cap {{ color:var(--muted); font-size:.92rem; }}
.td-call .big {{ font:700 2.7rem/1.1 var(--serif); margin:.3rem 0 .25rem; color:var(--navy); }}
.td-call.risk .big {{ color:var(--risk); }}
.td-call.agreed .big {{ color:var(--agreed); }}
.td-chips {{ display:flex; flex-wrap:wrap; gap:.45rem; margin-top:1rem; }}
.td-chip {{ border:1px solid var(--rule); padding:.28rem .65rem; font-size:.88rem; border-radius:2px; background:#fff; }}
.td-chip b {{ font-weight:700; margin-left:.25rem; }}
.td-jump {{ display:flex; align-items:center; justify-content:center; min-height:2.5rem; padding:0 .8rem;
  background:#fff; border:1px solid var(--rule); border-radius:2px; color:var(--navy) !important;
  text-decoration:none !important; font-weight:500; }}
.td-jump:hover {{ border-color:var(--navy); }}
{"".join(f".td-chip.{t} {{ color:{c}; border-color:{b}; background:{bg}; }}" for t, (c, b, bg) in TONES.items())}

/* Note headings: the anchor every note reference jumps to */
.td-noteh {{ display:flex; align-items:baseline; gap:.75rem; flex-wrap:wrap; border-bottom:1px solid var(--rule);
  padding-bottom:.45rem; margin:2.3rem 0 .8rem; scroll-margin-top:4.5rem; }}
.td-noteh .n {{ font:600 1.25rem var(--serif); color:var(--ochre-text); white-space:nowrap; }}
.td-noteh .t {{ font:600 1.25rem var(--serif); color:var(--navy); }}
.td-noteh .c {{ margin-left:auto; color:var(--muted); font-size:.9rem; }}
.td-noteh:target {{ background:#FBF4E6; }}
.td-ntot {{ margin:.1rem 0 1.6rem; }}
.td-ntot div {{ display:flex; justify-content:space-between; gap:1rem; padding:.5rem .1rem .45rem;
  border-top:1px solid var(--navy); border-bottom:3px double var(--navy); font-weight:600; color:var(--navy); }}
.td-ntot div + div {{ border-top:0; }}
.td-ntot b {{ white-space:nowrap; }}

/* Approval block: the human in the loop, written into the statement */
.td-sign {{ display:grid; grid-template-columns:1.3fr 1fr 1fr; background:#fff; border:1px solid var(--rule);
  margin:2.2rem 0 .6rem; }}
.td-sign div {{ padding:.8rem 1rem .9rem; border-right:1px solid var(--rule); font-size:.78rem; letter-spacing:.06em;
  text-transform:uppercase; color:var(--muted); }}
.td-sign div:last-child {{ border-right:0; }}
.td-sign b {{ display:block; font-size:.95rem; letter-spacing:0; text-transform:none; font-weight:600;
  color:var(--navy); min-height:1.5em; margin-top:.3rem; }}
.td-sign .blank b {{ border-bottom:1px solid var(--muted); }}

/* Contents on the home page */
.td-intro {{ background:#fff; border:1px solid var(--rule); padding:1rem 1.25rem; margin:0 0 1.6rem; max-width:72ch; }}
.td-intro b {{ margin-right:.35rem; }}
.td-contents {{ font:600 1.3rem var(--serif); border-bottom:1px solid var(--navy); padding-bottom:.45rem; margin:0; }}
[class*="st-key-td-index-row"] {{ background:#fff; border:1px solid var(--rule); border-top:0; padding:1rem 1.2rem; }}
.td-idx-t {{ font:600 1.2rem var(--serif); color:var(--navy); }}

/* Streamlit pieces in the report's vocabulary */
[data-testid="stExpander"] details {{ border-radius:2px; background:#fff; border-color:var(--rule); }}
[data-testid="stAlertContainer"] {{ border:1px solid var(--rule); border-radius:2px; background-repeat:no-repeat;
  background-position:.9rem .95rem; background-size:20px 20px; padding-left:2.9rem; }}
[data-testid="stAlertContainer"] p, [data-testid="stAlertContainer"] div {{ color:var(--navy) !important; }}
{_ALERT_CSS}
[data-testid="stElementContainer"]:has([data-testid="stAlert"]) + [data-testid="stElementContainer"]:has([data-testid="stDataFrame"]) {{ margin-top:1.2rem; }}
.td-footer {{ font-size:.82rem; color:var(--muted); text-align:center; padding:.4rem 0 1rem; }}
.td-nb {{ white-space:nowrap; }}

@media (max-width: 640px) {{
  .block-container {{ padding-left:1rem; padding-right:1rem; padding-top:3.8rem; }}
  .td-head {{ flex-direction:column; align-items:flex-start; gap:.4rem; }}
  .td-meta {{ text-align:left; white-space:normal; }}
  .td-head h1 {{ font-size:1.8rem; }}
  .td-stmt {{ padding:1rem .9rem .8rem; }}
  .td-stmt table {{ font-size:.88rem; }}
  .td-stmt td, .td-stmt th {{ padding-left:.25rem; padding-right:.25rem; }}
  .td-stmt td.ref {{ width:2.4rem; }}
  .td-call .big {{ font-size:2.1rem; }}
  .td-sign {{ grid-template-columns:1fr; }}
  .td-sign div {{ border-right:0; border-bottom:1px solid var(--rule); }}
  .td-noteh .c {{ margin-left:0; width:100%; }}
  /* keep the dataframe hover toolbar off the note heading above the table */
  [data-testid="stElementContainer"]:has([data-testid="stDataFrame"]) {{ margin-top:2.1rem; }}
}}
</style>
"""


def setup_page(title: str, icon: str = ":material/receipt_long:") -> None:
    """Call first on every page: browser title/icon, wide layout, the report CSS and sidebar label."""
    st.set_page_config(page_title=f"{title} | TaxDesk", page_icon=icon, layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)
    st.sidebar.markdown(
        f"<div class='td-side'><b>TaxDesk</b>Tax year {get_rule('meta.tax_year')}<br>Synthetic data only</div>",
        unsafe_allow_html=True)


def footer() -> None:
    """The disclaimer footer required on every page."""
    st.divider()
    st.markdown(f"<div class='td-footer'>{get_rule('meta.disclaimer')}</div>", unsafe_allow_html=True)


def rupees(value: float, decimals: int = 0) -> str:
    """'₹12,34,568' in Indian grouping, for headline numbers."""
    return "₹" + format_inr(value, decimals)


def page_header(title: str, subtitle: str = "", meta: str = "", meta_strong: str = "", target=None) -> None:
    """Title and subtitle on the left; client (bold) and period/meta on the right.

    Pass `target` (an st.empty() placeholder) to draw the header late, once results are known.
    """
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    strong = f"<b>{escape(meta_strong)}</b>" if meta_strong else ""
    html = (f"<div class='td-head'><div><h1>{escape(title)}</h1>{sub}</div>"
            f"<div class='td-meta'>{strong}{escape(meta)}</div></div>")
    (target or st).markdown(html, unsafe_allow_html=True)


@dataclass
class Line:
    """One row of a statement.

    kind: "line" (plain), "less" (shown in brackets), "sub" (subtotal, ruled above),
    "total" (ruled above, double-ruled below), "risk" (money at risk, in red) or "memo" (muted).
    values: one entry per amount column; numbers are formatted in Indian grouping, strings shown as is.
    """

    label: str
    values: list[float | int | str | None] = field(default_factory=list)
    note: int | str | None = None
    kind: str = "line"


def _cell(value: float | int | str | None, bracket: bool, decimals: int = 0) -> str:
    """Format one statement amount: Indian grouping, brackets for deductions, blank for None.

    Integers (counts) never show decimals; floats show `decimals` places.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return escape(value)
    if bracket and value == 0:
        return "–"                       # nothing deducted
    text = format_inr(abs(value), 0 if isinstance(value, int) else decimals)
    return f"({text})" if bracket or value < 0 else text


_RS = re.compile(r"Rs\.? ?(\d[\d,]*(?:\.\d+)?)")


def inr_text(text: str) -> str:
    """Rewrite 'Rs 125,000' style amounts inside a sentence as '₹1,25,000' (Indian grouping)."""
    def repl(m: re.Match) -> str:
        raw = m.group(1).replace(",", "")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        return "₹" + format_inr(float(raw), decimals)
    return _RS.sub(repl, text)


def _note_link(note: int | str | None) -> str:
    """The ochre note reference; a number links to that note's heading on the page."""
    if note is None:
        return ""
    first = str(note).split("–")[0].split(",")[0].strip()
    return f"<a href='#note-{escape(first)}' aria-label='See note {escape(str(note))}'>{escape(str(note))}</a>"


def statement_html(title: str, headers: list[str], lines: list[Line], pick: str | None = None,
                   decimals: int = 0) -> str:
    """The statement as HTML (title, header row, lines). A Note column appears when any line has a note."""
    has_notes = any(ln.note is not None for ln in lines)
    first, amounts = headers[0], headers[1:]
    head = f"<th>{escape(first)}</th>" + ("<th>Note</th>" if has_notes else "")
    head += "".join(f"<th class='{'pick' if h == pick else ''}'>{escape(h)}</th>" for h in amounts)
    rows = []
    for ln in lines:
        cells = [f"<td>{escape(ln.label)}</td>"]
        if has_notes:
            cells.append(f"<td class='ref'>{_note_link(ln.note)}</td>")
        for h, v in zip(amounts, ln.values):
            cells.append(f"<td class='amt{' pick' if h == pick else ''}'>{_cell(v, ln.kind == 'less', decimals)}</td>")
        rows.append(f"<tr class='{ln.kind}'>{''.join(cells)}</tr>")
    heading = f"<h2>{escape(title)}</h2>" if title else ""
    return (f"<div class='td-stmt'>{heading}<table><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def statement(title: str, headers: list[str], lines: list[Line], pick: str | None = None,
              decimals: int = 0) -> None:
    """Draw a statement. `pick` names the amount column whose total is marked (e.g. the cheaper regime)."""
    st.markdown(statement_html(title, headers, lines, pick, decimals), unsafe_allow_html=True)


def note_total(rows: list[tuple[str, float]], decimals: int = 2) -> None:
    """The closing total(s) of a note, ruled like a statement total, so it ties to the statement line."""
    body = "".join(f"<div><span>{escape(label)}</span><b>₹{format_inr(amount, decimals)}</b></div>"
                   for label, amount in rows)
    st.markdown(f"<div class='td-ntot'>{body}</div>", unsafe_allow_html=True)


def chips_html(items: list[tuple[str, int | None, str]]) -> str:
    """Status chips: (label, count or None, tone) with tone agreed / review / risk / neutral."""
    spans = "".join(f"<span class='td-chip {tone}'>{escape(label)}{f'<b>{n:,}</b>' if n is not None else ''}</span>"
                    for label, n, tone in items)
    return f"<div class='td-chips'>{spans}</div>"


def callout(caption: str, value: str, text: str = "", tone: str = "neutral",
            chips: list[tuple[str, int | None, str]] | None = None) -> None:
    """The headline figure beside a statement, with an explanation and optional status chips."""
    body = f"<div class='cap'>{escape(text)}</div>" if text else ""
    st.markdown(f"<div class='td-call {tone}'><div class='cap'>{escape(caption)}</div>"
                f"<div class='big'>{escape(value)}</div>{body}{chips_html(chips) if chips else ''}</div>",
                unsafe_allow_html=True)


def note_heading(number: int, title: str, count: str = "") -> None:
    """A numbered note heading; statement references jump here (#note-<number>)."""
    c = f"<span class='c'>{escape(count)}</span>" if count else ""
    st.markdown(f"<div class='td-noteh' id='note-{number}' role='heading' aria-level='2'>"
                f"<span class='n'>Note {number}</span><span class='t'>{escape(title)}</span>{c}</div>",
                unsafe_allow_html=True)


def intro_note(label: str, text: str) -> None:
    """A boxed statement on the home page (used for the human-in-the-loop principle)."""
    st.markdown(f"<div class='td-intro'><b>{escape(label)}</b>{escape(text)}</div>", unsafe_allow_html=True)


def signoff(prepared_for: str = "") -> None:
    """Approval block: TaxDesk prepares; a person reviews and signs."""
    who = f"TaxDesk{(' for ' + escape(prepared_for)) if prepared_for else ''}, {date.today():%d-%m-%Y}"
    st.markdown(
        f"<div class='td-sign'><div>Prepared by<b>{who}</b></div>"
        "<div class='blank'>Reviewed by<b></b></div><div class='blank'>Date<b></b></div></div>",
        unsafe_allow_html=True)


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


STATUS_TONES = {"Agreed": "agreed", "Not in 2B": "risk", "At risk": "risk", "Needs review": "review",
                "Difference": "review", "Not in books": "neutral"}


STYLE_ROW_LIMIT = 3000   # above this, skip the Styler (slow) and fall back to plain 2-decimal numbers


def _decimals(col: str) -> int:
    """Places to show for a float column: NAVs and units 4, similarity scores 1, rupee amounts 2."""
    if "NAV" in col or col.startswith("Units"):
        return 4
    return 1 if col == "Similarity" else 2


def show_table(df: pd.DataFrame, height: int | None = None, status_col: str | None = None,
               labels: dict[str, str] | None = None, widths: dict[str, int | str] | None = None,
               places: dict[str, int] | None = None) -> None:
    """A read-only, full-width table with amounts in Indian grouping (₹ style, fixed decimals).

    `status_col` words are coloured by tone; `labels` renames displayed headers;
    `widths` sets column widths ("small" / "medium" / "large" or pixels); `places` overrides decimals.
    """
    kwargs = {"height": height} if height else {}
    labels, widths = labels or {}, widths or {}
    floats = [c for c in df.columns if pd.api.types.is_float_dtype(df[c])]
    styled = len(df) <= STYLE_ROW_LIMIT
    config = table_config(df)
    for col in df.columns:
        label, width = labels.get(col, col), widths.get(col)
        if col in floats:
            config[col] = (st.column_config.Column(label, width=width) if styled else
                           st.column_config.NumberColumn(label, width=width, format=f"%.{_decimals(col)}f"))
        elif col in labels or col in widths:
            config[col] = (st.column_config.DateColumn(label, width=width, format="DD-MM-YYYY")
                           if pd.api.types.is_datetime64_any_dtype(df[col])
                           else st.column_config.Column(label, width=width))
    data: pd.DataFrame | pd.io.formats.style.Styler = df
    if styled:
        style = df.style
        for col in floats:
            dp = (places or {}).get(col, _decimals(col))
            style = style.format(lambda v, p=dp: "" if pd.isna(v) else
                                 (f"({format_inr(-v, p)})" if v < 0 else format_inr(v, p)), subset=[col])
        if status_col and status_col in df.columns:
            style = style.map(lambda v: f"color:{TONES[STATUS_TONES.get(v, 'neutral')][0]};font-weight:700",
                              subset=[status_col])
        data = style
    st.dataframe(data, hide_index=True, column_config=config, width="stretch", **kwargs)


def table_height(rows: int, cap: int = 12) -> int | None:
    """A dataframe height that shows up to `cap` rows, so long notes scroll inside their table."""
    return None if rows <= cap else 38 + 35 * cap
