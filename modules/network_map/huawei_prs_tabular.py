"""
Huawei PRS CSV/XLSX exports often include preamble rows; the real table starts
where column A (first column) is exactly ``Date`` — that row is the header.
"""

from __future__ import annotations

import csv
import os
from io import StringIO

import pandas as pd


def _cell_a1_normalized(val: object) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    if s.startswith("\ufeff"):
        s = s.lstrip("\ufeff").strip()
    return s.lower()


def _header_row_index_date_in_col_a(raw: pd.DataFrame) -> int | None:
    if raw is None or raw.empty or raw.shape[1] == 0:
        return None
    col0 = raw.iloc[:, 0]
    for i in range(len(raw)):
        if _cell_a1_normalized(col0.iloc[i]) == "date":
            return int(i)
    return None


def _make_unique_original_headers(header_vals: list[object]) -> list[str]:
    out: list[str] = []
    seen: dict[str, int] = {}
    for i, v in enumerate(header_vals):
        base = str(v).strip() if v is not None and not (isinstance(v, float) and pd.isna(v)) else ""
        if not base:
            base = f"empty_col_{i}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        if n:
            base = f"{base}_{n + 1}"
        out.append(base)
    return out


def _text_matrix_csv_reader(text: str, delimiter: str) -> pd.DataFrame:
    """Build a ragged matrix (padded) — pandas rejects preamble + grid row width changes."""
    rows = list(csv.reader(StringIO(text), delimiter=delimiter))
    if not rows:
        return pd.DataFrame()
    mx = max(len(r) for r in rows)
    if mx == 0:
        return pd.DataFrame()
    grid = [(r + [""] * (mx - len(r))) for r in rows]
    return pd.DataFrame(grid, dtype=str)


def _read_csv_matrix_flexible(path: str) -> pd.DataFrame:
    """
    PRS preamble lines are often single-field while the grid is ``;`` or tab or ``,`` separated.
    Prefer the delimiter where column A contains a ``Date`` header row (typical PRS export).
    """
    text: str | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, encoding=encoding, newline="") as f:
                text = f.read()
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise OSError(f"cannot decode text: {path}")
    last_ok: pd.DataFrame | None = None
    for sep in (";", "\t", ","):
        df = _text_matrix_csv_reader(text, sep)
        if df.empty or df.shape[1] == 0:
            continue
        last_ok = df
        if _header_row_index_date_in_col_a(df) is not None:
            return df
    if last_ok is not None:
        return last_ok
    return pd.DataFrame()


def _read_raw_matrix(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(path, header=None, dtype=str, engine="openpyxl")
    return _read_csv_matrix_flexible(path)


def _read_legacy_first_row_header(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(path, dtype=str, engine="openpyxl")
    raw = _read_csv_matrix_flexible(path)
    if raw.empty or raw.shape[0] == 0:
        return raw
    header = raw.iloc[0].astype(str).str.strip()
    body = raw.iloc[1:].copy()
    body.columns = _make_unique_original_headers(header.tolist())
    return body.reset_index(drop=True)


def read_huawei_prs_tabular(path: str, *, log: str | None = None) -> pd.DataFrame:
    """
    Drop preamble rows until the row whose column A is ``Date``; that row becomes the header.
    Drops all-blank rows and rows with an empty column A after the header.
    """
    prefix = log or "huawei-prs"
    raw = _read_raw_matrix(path)
    idx = _header_row_index_date_in_col_a(raw)
    if idx is None:
        print(f"[{prefix}] no 'Date' in column A in {path}; using first-line header fallback")
        return _read_legacy_first_row_header(path)

    header_vals = raw.iloc[idx].tolist()
    originals = _make_unique_original_headers(header_vals)
    body = raw.iloc[idx + 1 :].copy()
    body.columns = originals
    body = body.dropna(how="all").reset_index(drop=True)
    if not body.empty and body.shape[1] > 0:
        d = body.iloc[:, 0].astype(str).str.strip()
        body = body.loc[d.ne("") & d.str.lower().ne("nan")].reset_index(drop=True)
    return body
