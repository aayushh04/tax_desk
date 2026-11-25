"""Read uploaded Excel/CSV files robustly, entirely in memory (nothing is written to disk).

Real exports are messy: title rows above the header, two-row headers made of merged
cells (the GSTR-2B Excel from the portal does this), blank rows, odd encodings. This
module turns any of that into a plain DataFrame whose columns are the header texts.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import IO

import pandas as pd
from rapidfuzz import fuzz

HEADER_SCAN_ROWS = 25


class TableReadError(ValueError):
    """Raised with a user-friendly message when a file cannot be read."""


def norm_header(text: object) -> str:
    """Lowercase a header and turn every run of non-letters/digits into one space.

    'Invoice Value(₹)' -> 'invoice value', 'State/UT Tax' -> 'state ut tax'.
    """
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _is_blank(value: object) -> bool:
    """True for None, NaN and empty/whitespace strings."""
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _header_score(cells: Iterable[object], expected: list[str]) -> int:
    """How many cells in a row look like one of the expected header names."""
    score = 0
    for cell in cells:
        h = norm_header(cell)
        if h and any(h == e or fuzz.ratio(h, e) >= 88 for e in expected):
            score += 1
    return score


def _merge_rows(upper: list[object], lower: list[object]) -> list[object]:
    """Combine a two-row header: use the lower cell when filled, otherwise the upper (merged) cell."""
    return [lo if not _is_blank(lo) else up for up, lo in zip(upper, lower)]


def find_header(raw: pd.DataFrame, expected_headers: Iterable[str]) -> tuple[int, int, list[object]]:
    """Locate the header in the first rows of a sheet.

    Returns (first header row index, number of header rows (1 or 2), header cells).
    """
    expected = [norm_header(e) for e in expected_headers if norm_header(e)]
    rows = [list(raw.iloc[i]) for i in range(min(HEADER_SCAN_ROWS, len(raw)))]
    if not rows:
        raise TableReadError("The file is empty.")
    if not expected:
        return 0, 1, rows[0]
    scores = [_header_score(r, expected) for r in rows]
    best = max(range(len(rows)), key=lambda i: scores[i])
    choice = (best, 1, rows[best], scores[best])
    for top in (best - 1, best):                      # try a two-row header around the best row
        if 0 <= top and top + 1 < len(rows):
            merged = _merge_rows(rows[top], rows[top + 1])
            s = _header_score(merged, expected)
            if s > choice[3]:
                choice = (top, 2, merged, s)
    return choice[0], choice[1], choice[2]


def _unique_columns(cells: list[object]) -> list[str]:
    """Turn header cells into unique, non-empty column names."""
    names: list[str] = []
    seen: dict[str, int] = {}
    for i, cell in enumerate(cells):
        name = f"Column {i + 1}" if _is_blank(cell) else str(cell).strip()
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        names.append(name)
    return names


def _read_csv_rows(data: bytes) -> pd.DataFrame:
    """Read CSV bytes into a raw grid of strings, tolerating ragged rows and Excel's encodings."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise TableReadError("Could not read the CSV text encoding. Save it as UTF-8 CSV and retry.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    width = max((len(r) for r in rows), default=0)
    return pd.DataFrame([r + [""] * (width - len(r)) for r in rows], dtype=object)


def excel_sheet_names(data: bytes) -> list[str]:
    """List the sheet names in an Excel file (for the 'which sheet?' picker)."""
    try:
        return pd.ExcelFile(io.BytesIO(data), engine="openpyxl").sheet_names
    except Exception as exc:  # noqa: BLE001 - any parser failure becomes a friendly message
        raise TableReadError(f"Could not open the Excel file ({exc.__class__.__name__}).") from exc


def read_table(source: bytes | str | Path | IO[bytes], filename: str | None = None,
               sheet: str | int | None = None,
               expected_headers: Iterable[str] = (),
               prefer_sheet_containing: str | None = None) -> pd.DataFrame:
    """Read an .xlsx or .csv into a DataFrame, finding the real header row automatically.

    `source` can be raw bytes, a path, or a file-like object (like Streamlit's upload).
    All cells are kept as raw values; cleaning and type conversion happen later.
    The 1-based spreadsheet row number of the first data row is stored in
    df.attrs["first_data_row"], so error messages can say "row 14".
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        filename = filename or path.name
        data = path.read_bytes()
    elif isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        filename = filename or getattr(source, "name", None)
        data = source.read()
    ext = Path(filename or "").suffix.lower()

    if ext in {".xlsx", ".xlsm"}:
        names = excel_sheet_names(data)
        if sheet is None:
            sheet = names[0]
            if prefer_sheet_containing:
                sheet = next((n for n in names if prefer_sheet_containing.lower() in n.lower()), sheet)
        try:
            raw = pd.read_excel(io.BytesIO(data), sheet_name=sheet, header=None, dtype=object,
                                engine="openpyxl")
        except Exception as exc:  # noqa: BLE001
            raise TableReadError(f"Could not read sheet {sheet!r} ({exc.__class__.__name__}).") from exc
    elif ext in {".csv", ".txt"}:
        raw = _read_csv_rows(data)
    elif ext == ".xls":
        raise TableReadError("Old .xls files are not supported. Open it in Excel and save as .xlsx.")
    else:
        raise TableReadError(f"Unsupported file type '{ext or '?'}'. Upload an .xlsx or .csv file.")

    if raw.empty:
        raise TableReadError("The file has no rows.")
    header_idx, n_header_rows, cells = find_header(raw, expected_headers)
    df = raw.iloc[header_idx + n_header_rows:].copy()
    df.columns = _unique_columns(cells)
    # Drop columns that have no header and no data (common in Excel exports)
    empty_cols = [c for c in df.columns if c.startswith("Column ") and df[c].map(_is_blank).all()]
    df = df.drop(columns=empty_cols).reset_index(drop=True)
    df.attrs["first_data_row"] = header_idx + n_header_rows + 1
    return df


# =============================================================== cell parsing =====

def _blank_mask(s: pd.Series) -> pd.Series:
    """True where a cell is empty, NaN, or a placeholder like '-'."""
    text = s.astype(object).where(s.notna(), "").astype(str).str.strip()
    return text.isin(["", "-", "nan", "NaN", "None", "NaT"])


def parse_amounts(s: pd.Series, decimals: int = 2) -> tuple[pd.Series, pd.Series]:
    """Turn messy amount cells into floats. Returns (values, bad_mask).

    Handles '1,23,456.50', 'Rs 500', '₹500', '(250)' (negative), blanks (-> 0).
    Text that is not a number becomes 0 and is flagged in bad_mask.
    """
    blank = _blank_mask(s)
    text = s.astype(object).where(~blank, "").astype(str).str.strip()
    text = text.str.replace(r"(?i)(rs\.?|inr|₹|,|\s)", "", regex=True)
    negative = text.str.match(r"^\(.*\)$")
    text = text.str.replace(r"[()]", "", regex=True)
    values = pd.to_numeric(text.where(~blank, None), errors="coerce").astype(float)
    values = values.where(~negative, -values)
    bad = values.isna() & ~blank
    return values.fillna(0.0).round(decimals), bad


_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d-%b-%Y", "%d-%b-%y",
                 "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d %H:%M:%S")
_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _to_timestamp(value: object) -> pd.Timestamp | None:
    """Parse one date cell. Returns None if it cannot be parsed. Day comes before month (Indian style)."""
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 20000 <= value <= 80000:                     # an Excel serial date number
            return _EXCEL_EPOCH + pd.Timedelta(days=float(value))
        return None
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return pd.Timestamp(datetime.strptime(text, fmt))
        except ValueError:
            continue
    try:
        return pd.Timestamp(pd.to_datetime(text, dayfirst=True))
    except (ValueError, TypeError):
        return None


def parse_dates(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse a column of dates in any common format. Returns (dates, bad_mask)."""
    blank = _blank_mask(s)
    cache: dict[str, pd.Timestamp | None] = {}
    out: list[pd.Timestamp | None] = []
    for value, is_blank in zip(s.tolist(), blank.tolist()):
        if is_blank:
            out.append(None)
            continue
        key = repr(value)
        if key not in cache:
            cache[key] = _to_timestamp(value)
        out.append(cache[key])
    dates = pd.to_datetime(pd.Series(out, index=s.index, dtype=object), errors="coerce")
    return dates, dates.isna() & ~blank
