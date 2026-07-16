"""
PM Data Processor
=================
Reads hourly KPI XLSX/XLS/CSV files and loads data into the appropriate PM database.

Nokia:  one file per technology → each file has many cells as rows
Huawei: same hourly tables as Nokia (``2G_Hourly`` … ``5G_Hourly`` in ``huawei_pm_cells.db``); ingest like Nokia PM (CSV / workbook → ``_insert_df``).

Scheduled sync can use **incremental** upserts (``PM_SYNC_MODE`` in ``sync_config``) instead of wiping
all rows every cycle; optional **``PM_RETENTION_DAYS``** prunes old timestamps.

No column mapping configuration is required.  The code auto-detects which
column holds the cell name and which holds the timestamp by scanning column
names for well-known keywords.  All other columns are stored as-is using
the original header names, so charts can display them unchanged.
"""

import sqlite3
import logging
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from functools import partial
import csv
import io

import sys
import os
import re
import zipfile
import tempfile
import shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from sync_config import (
    NOKIA_PM_DB,
    HUAWEI_PM_DB,
    pm_table_name,
    PM_TECHNOLOGIES,
    PM_SYNC_FULL_CLEAR,
    PM_INSERT_BATCH_SIZE,
)

logger = logging.getLogger(__name__)

# Nokia/Huawei PM SQLite: parallel per-RAT writers contend on one file — cap workers and use busy_timeout.
try:
    _PM_PARALLEL_CAP = max(1, min(5, int((os.environ.get('PM_INGEST_PARALLEL_WORKERS') or '5').strip())))
except ValueError:
    _PM_PARALLEL_CAP = 5


def _parallel_pm_zeroarg_tasks(
    tasks: list[tuple[str, object]],
    *,
    max_workers: int | None = None,
) -> dict:
    """
    Run zero-argument callables in parallel; each should wrap real work in
    :func:`functools.partial` so loop variables are captured safely.

    Returns ``{result_key: return_value}``. Single-task lists run inline (no threads).
    """
    if len(tasks) <= 1:
        return {key: fn() for key, fn in tasks}
    mw = max_workers if max_workers is not None else _PM_PARALLEL_CAP
    mw = max(1, min(mw, len(tasks)))
    out: dict = {}
    with ThreadPoolExecutor(max_workers=mw) as pool:
        fut_map = {pool.submit(fn): key for key, fn in tasks}
        for fut in as_completed(fut_map):
            key = fut_map[fut]
            try:
                out[key] = fut.result()
            except Exception as e:
                logger.exception('Parallel PM task failed key=%r', key)
                out[key] = e
    return out


def _huawei_pm_debug() -> bool:
    """Set ``HUAWEI_PM_DEBUG=1`` (or ``true``/``yes``/``on``) for stderr + detailed Huawei PM / PMLoad traces."""
    v = (os.environ.get('HUAWEI_PM_DEBUG') or '').strip().lower()
    return v in ('1', 'true', 'yes', 'on')


def _huawei_pm_trace(msg: str, *args: object) -> None:
    text = msg % args if args else msg
    logger.info('[HuaweiPM] %s', text)
    if _huawei_pm_debug():
        print(f'[HuaweiPM] {text}', file=sys.stderr, flush=True)


def _pm_load_trace(trace: bool, msg: str, *args: object) -> None:
    if not trace:
        return
    text = msg % args if args else msg
    logger.info('[PMLoad] %s', text)
    print(f'[PMLoad] {text}', file=sys.stderr, flush=True)


# Keywords used to auto-detect the cell_name column (order matters — more specific first).
# - Never use bare ``bts``: it matches ``MRBTS`` / ``LNBTS`` / ``NRBTS`` and hijacks 4G/5G.
# - ``wcel`` alone matches ``WCEL ID``; skip *ID columns so we can fall through to ``DN``.
# - ``dn`` (before generic ``name``) avoids ``PLMN name`` / ``BSC name`` on Nokia exports.
_CELL_KEYWORDS = [
    'nrcel name', 'nrcelname', 'nrcel',
    'lncel name', 'lncelname', 'lncel',
    'wcel name', 'wcelname', 'wcel',
    'bts name', 'btsname', 'bts',
    'cell name', 'cell_name', 'cellname',
    'user label', 'ne name', 'cgi', 'meas obj', 'measobj',
    'dn',
    'cell', 'name', 'trans',
]

_DUPLICATE_KPI_NAMES = {
    'RH303:Handover Success Rate(%)',
    'K3034:TCHH Traffic Volume(Erl)',
    'Drop Call Rate',
    'CS RAB Congestion Num',
    'TCH raw block.1',
    'Act HS-DSCH  end usr thp',
    'Expect cell size',
    'Avg PDCP cell thp UL',
    'TRS_SLOT_PDSCH (M55308C00017)',
}
# Timestamp column detection: put **date** before bare **time** so Huawei "Date" wins over
# KPI columns like "Latency time" that contain 0 → pandas epoch (1970) and collapse history
# under UNIQUE(cell_name, timestamp).
_TS_KEYWORDS   = ['period start', 'period', 'date', 'timestamp', 'start', 'time']


# ---------------------------------------------------------------------------
# File reader — tries multiple engines so corrupted/old-format files work
# ---------------------------------------------------------------------------

def _concatenated_kpi_style_headers(df: pd.DataFrame) -> int:
    """
    Count column names that look like several NetAct KPI labels jammed into one
    header (wrong CSV delimiter — usually comma read where semicolon is correct).
    """
    n = 0
    for c in df.columns:
        s = str(c)
        if ';' in s and len(s) > 50:
            n += 1
    return n


def _nokia_csv_parse_score(df: pd.DataFrame) -> float:
    """Higher is better: many real columns, few concatenated-looking headers."""
    if df is None or len(df.columns) < 2:
        return float('-inf')
    bad = _concatenated_kpi_style_headers(df)
    return len(df.columns) * 1000.0 - bad * 250.0


def _read_nokia_csv_best(path: str, *, nrows: int | None = None) -> pd.DataFrame | None:
    """
    Nokia / NetAct hourly exports are often semicolon-separated.
    Try encodings × delimiters and pick the parse with the best score.

    ``nrows`` limits how many rows are read (headers stay correct); use for inspection
    on huge files — omit for full ingest.
    """
    file_size = 0
    try:
        file_size = os.path.getsize(path)
    except OSError:
        pass
    file_size_mb = file_size / (1024 * 1024) if file_size else 0.0

    best: pd.DataFrame | None = None
    best_score = float('-inf')

    use_chunk = file_size_mb >= 80 and nrows is None

    for encoding in (
        'utf-8-sig',
        'utf-8',
        'utf-16',
        'utf-16-le',
        'utf-16-be',
        'latin-1',
        'cp1252',
        'iso-8859-1',
    ):
        for sep in (';', '\t', ',', '|'):
            try:
                if use_chunk:
                    chunks = []
                    for chunk in pd.read_csv(
                        path,
                        sep=sep,
                        dtype=str,
                        encoding=encoding,
                        engine='python',
                        on_bad_lines='skip',
                        chunksize=50000,
                    ):
                        chunks.append(chunk)
                    df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
                else:
                    df = pd.read_csv(
                        path,
                        sep=sep,
                        dtype=str,
                        encoding=encoding,
                        engine='python',
                        on_bad_lines='skip',
                        nrows=nrows,
                    )
            except Exception:
                continue
            if len(df.columns) < 2:
                continue
            sc = _nokia_csv_parse_score(df)
            if sc > best_score:
                best_score = sc
                best = df

    if best is not None:
        logger.info(
            'Nokia CSV parse pick: path=%s cols=%s concat_like_headers=%s',
            path,
            len(best.columns),
            _concatenated_kpi_style_headers(best),
        )
    return best


def _load_pm_file(file_path, *, trace: bool = False):
    """
    Return a DataFrame from an XLSX, XLS, or CSV file.
    Nokia NetAct and Huawei U2000 often export files with a .xlsx extension
    that are actually HTML tables or tab/comma-delimited text in non-UTF-8
    encoding (latin-1, cp1252).  We try every plausible format.

    Pass ``trace=True`` (or set env ``HUAWEI_PM_DEBUG`` from Huawei readers) to log each major stage.
    """
    file_size = 0
    try:
        file_size = os.path.getsize(file_path)
    except OSError:
        pass
    file_size_mb = file_size / (1024 * 1024) if file_size else 0.0

    logger.info('PM load: start file=%s size_mb=%.2f', file_path, file_size_mb)
    _pm_load_trace(
        trace,
        'start %s size_bytes=%s (set HUAWEI_PM_DEBUG=1 for this trace from Huawei ZIP)',
        os.path.basename(file_path),
        file_size,
    )

    # 1. Real XLSX (ZIP-based Office Open XML)
    try:
        df = pd.read_excel(file_path, engine='openpyxl')
        logger.info('PM load: read_excel(openpyxl) success rows=%s cols=%s', len(df), len(df.columns))
        return df
    except Exception as e:
        _pm_load_trace(trace, 'openpyxl failed: %s', e)

    # 2. Old binary XLS (BIFF format)
    try:
        df = pd.read_excel(file_path, engine='xlrd')
        logger.info('PM load: read_excel(xlrd) success rows=%s cols=%s', len(df), len(df.columns))
        return df
    except Exception as e:
        _pm_load_trace(trace, 'xlrd failed: %s', e)

    # 3. HTML table disguised as .xlsx (common Nokia NetAct export)
    try:
        dfs = pd.read_html(file_path, encoding='utf-8')
        if dfs and len(dfs[0].columns) > 1:
            logger.info('PM load: read_html(utf-8) success rows=%s cols=%s', len(dfs[0]), len(dfs[0].columns))
            return dfs[0]
        _pm_load_trace(trace, 'read_html utf-8: no table or single column')
    except Exception as e:
        _pm_load_trace(trace, 'read_html utf-8 failed: %s', e)
    try:
        dfs = pd.read_html(file_path, encoding='latin-1')
        if dfs and len(dfs[0].columns) > 1:
            logger.info('PM load: read_html(latin-1) success rows=%s cols=%s', len(dfs[0]), len(dfs[0].columns))
            return dfs[0]
        _pm_load_trace(trace, 'read_html latin-1: no table or single column')
    except Exception as e:
        _pm_load_trace(trace, 'read_html latin-1 failed: %s', e)

    def _sniff_delimiter(path: str, encoding: str) -> str | None:
        try:
            with open(path, 'r', encoding=encoding, errors='ignore') as fh:
                sample = fh.read(65536)
            if not sample or sample.count('\n') < 2:
                return None
            return csv.Sniffer().sniff(sample, delimiters=';,\t|').delimiter
        except Exception:
            return None

    def _read_csv_with_mode(path: str, sep: str, encoding: str) -> pd.DataFrame:
        # Large text exports are safer in chunks to avoid parser/memory spikes.
        if file_size_mb >= 80:
            chunks = []
            total_rows = 0
            for chunk in pd.read_csv(
                path,
                sep=sep,
                dtype=str,
                encoding=encoding,
                engine='python',
                on_bad_lines='skip',
                chunksize=50000,
            ):
                chunks.append(chunk)
                total_rows += len(chunk)
            df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
            logger.info(
                'PM load: chunked CSV success sep=%r enc=%s rows=%s cols=%s',
                sep, encoding, total_rows, len(df.columns)
            )
            return df
        df = pd.read_csv(
            path,
            sep=sep,
            dtype=str,
            encoding=encoding,
            engine='python',
            on_bad_lines='skip',
        )
        logger.info(
            'PM load: CSV success sep=%r enc=%s rows=%s cols=%s',
            sep, encoding, len(df), len(df.columns)
        )
        return df

    # 4. Text file (tab / comma / semicolon) in various encodings
    for encoding in ('utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1'):
        sniffed = _sniff_delimiter(file_path, encoding)
        # Prefer semicolon first — Nokia NetAct CSV KPI dumps are usually ';'-separated.
        seps = [';', '\t', ',']
        if sniffed in ('\t', ',', ';', '|'):
            seps = [sniffed] + [s for s in seps if s != sniffed]
            if sniffed == '|':
                seps.append('|')
        for sep in seps:
            try:
                df = _read_csv_with_mode(file_path, sep=sep, encoding=encoding)
                if len(df.columns) > 1:
                    logger.info(
                        'PM load: selected parser=csv file=%s sep=%r enc=%s cols=%s',
                        file_path, sep, encoding, len(df.columns)
                    )
                    return df
            except Exception:
                pass

    _pm_load_trace(trace, 'step4 (encoding×sep CSV): done — no multi-column frame yet')

    # 5. Last resort — pandas sniff (per encoding) + UTF-16 / fixed separators.
    # Avoid a single sep=None read that raises "Could not determine delimiter" with no fallback.
    for enc in ('latin-1', 'utf-8', 'utf-8-sig', 'cp1252', 'iso-8859-1'):
        try:
            df = pd.read_csv(
                file_path,
                sep=None,
                engine='python',
                dtype=str,
                encoding=enc,
                on_bad_lines='skip',
            )
            if len(df.columns) > 1:
                logger.info(
                    'PM load: fallback sniff success enc=%s rows=%s cols=%s',
                    enc,
                    len(df),
                    len(df.columns),
                )
                return df
        except Exception:
            pass
    for enc in ('utf-16', 'utf-16-le', 'utf-16-be'):
        for sep in ('\t', ';', ','):
            try:
                df = pd.read_csv(
                    file_path,
                    sep=sep,
                    engine='python',
                    dtype=str,
                    encoding=enc,
                    on_bad_lines='skip',
                )
                if len(df.columns) > 1:
                    logger.info(
                        'PM load: utf-16-style success enc=%s sep=%r rows=%s cols=%s',
                        enc,
                        sep,
                        len(df),
                        len(df.columns),
                    )
                    return df
            except Exception:
                pass

    _pm_load_trace(trace, 'step5 (sep=None + utf-16): done — no multi-column frame yet')

    # 6. Stdlib csv — avoids pandas ParserError / "Could not determine delimiter" on odd exports.
    def _looks_like_ooxml_or_ole_bin(path: str) -> bool:
        try:
            with open(path, 'rb') as fh:
                sig = fh.read(8)
        except OSError:
            return True
        if len(sig) >= 4 and sig[:2] == b'PK' and sig[2:4] in (b'\x03\x04', b'\x05\x06', b'\x07\x08'):
            return True
        return len(sig) >= 8 and sig[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'

    if not _looks_like_ooxml_or_ole_bin(file_path):
        head_bytes = min(max(file_size, 1), 4_000_000) if file_size else 2_000_000
        for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'utf-16', 'utf-16-le', 'utf-16-be'):
            try:
                with open(file_path, 'r', encoding=enc, errors='replace') as fh:
                    head = fh.read(head_bytes)
            except (UnicodeDecodeError, LookupError, OSError):
                continue
            if not head.strip():
                continue
            for delim in ('\t', ';', ',', '|'):
                try:
                    rows = list(csv.reader(io.StringIO(head), delimiter=delim))
                except Exception:
                    continue
                if len(rows) < 2:
                    continue
                sample = rows[: min(800, len(rows))]
                ncol = max((len(r) for r in sample), default=0)
                if ncol < 2:
                    continue
                try:
                    df = pd.read_csv(
                        file_path,
                        sep=delim,
                        dtype=str,
                        encoding=enc,
                        engine='python',
                        on_bad_lines='skip',
                    )
                    if len(df.columns) > 1:
                        logger.info(
                            'PM load: stdlib-csv pick sep=%r enc=%s rows=%s cols=%s',
                            delim,
                            enc,
                            len(df),
                            len(df.columns),
                        )
                        return df
                except Exception:
                    continue

    _pm_load_trace(trace, 'step6 (stdlib csv head): done — no multi-column frame yet')

    # 7. Regex whitespace columns (fixed-width-ish text dumps)
    if not _looks_like_ooxml_or_ole_bin(file_path):
        for enc in ('utf-8', 'latin-1', 'cp1252'):
            try:
                df = pd.read_csv(
                    file_path,
                    sep=r'\s+',
                    engine='python',
                    dtype=str,
                    encoding=enc,
                    on_bad_lines='skip',
                )
                if len(df.columns) > 1:
                    logger.info('PM load: regex-whitespace sep rows=%s cols=%s', len(df), len(df.columns))
                    return df
            except Exception:
                pass

    _pm_load_trace(trace, 'step7 (regex whitespace): done — no multi-column frame yet')

    # 8. XML tabular (some OSS / PRS exports); requires lxml (listed in requirements).
    if not _looks_like_ooxml_or_ole_bin(file_path):
        try:
            with open(file_path, 'rb') as fh:
                lead = fh.read(4096).lstrip()
            if lead.startswith(b'<?xml') or (
                lead.startswith(b'<')
                and b'<html' not in lead[:800].lower()
                and b'<!doctype html' not in lead[:800].lower()
            ):
                try:
                    df = pd.read_xml(file_path)
                    if df is not None and len(df.columns) > 1:
                        logger.info(
                            'PM load: read_xml success rows=%s cols=%s',
                            len(df),
                            len(df.columns),
                        )
                        return df
                except Exception as e:
                    _pm_load_trace(trace, 'read_xml failed: %s', e)
        except Exception as e:
            _pm_load_trace(trace, 'XML sniff branch error: %s', e)

    _pm_load_trace(trace, 'step8 (read_xml): done — no multi-column frame yet')

    # 9. Leading metadata / comment lines before the real header row.
    if not _looks_like_ooxml_or_ole_bin(file_path):
        for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'iso-8859-1'):
            for skip in (1, 2, 3, 4, 5, 6, 7, 8):
                for sep in (';', '\t', ',', '|'):
                    try:
                        df = pd.read_csv(
                            file_path,
                            sep=sep,
                            dtype=str,
                            encoding=enc,
                            engine='python',
                            on_bad_lines='skip',
                            skiprows=skip,
                            comment='#',
                        )
                        if len(df.columns) > 1:
                            logger.info(
                                'PM load: skiprows=%s comment=# sep=%r enc=%s rows=%s cols=%s',
                                skip,
                                sep,
                                enc,
                                len(df),
                                len(df.columns),
                            )
                            return df
                    except Exception:
                        pass

    _pm_load_trace(trace, 'step9 (skiprows+comment): done — giving up')

    def _load_pm_failure_hint(path: str) -> str:
        base = os.path.basename(path)
        try:
            with open(path, 'rb') as fh:
                raw = fh.read(256)
        except OSError as exc:
            return f'{base!r}: cannot read file ({exc})'
        if not raw:
            return f'{base!r}: empty file'
        if len(raw) >= 4 and raw[:2] == b'PK' and raw[2:4] in (b'\x03\x04', b'\x05\x06', b'\x07\x08'):
            return f'{base!r}: ZIP/OOXML signature (not a flat CSV — use workbook path or extract)'
        if len(raw) >= 8 and raw[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            return f'{base!r}: legacy XLS binary — try read_excel path or re-export as CSV'
        printable = sum(1 for b in raw if 32 <= b < 127 or b in (9, 10, 13))
        if printable / max(len(raw), 1) < 0.55:
            return f'{base!r}: non-text start hex={raw[:48].hex()}'
        line = raw.decode('utf-8', errors='replace').split('\n', 1)[0][:140]
        return f'{base!r}: first line={line!r}'

    hint = _load_pm_failure_hint(file_path)
    _pm_load_trace(trace, 'FAILED %s', hint)
    raise ValueError(
        'Could not load PM file as Excel, HTML, XML, or delimited text. '
        'If the archive is a .zip, confirm it contains a valid '
        '.xlsx/.xlsm/.csv/.txt/.tsv for PM counters. '
        f'{hint}'
    )


# ---------------------------------------------------------------------------
# Auto-detect cell_name / timestamp columns
# ---------------------------------------------------------------------------

def _detect_col(columns, keywords):
    """Return the first column whose lower-case name contains any keyword."""
    col_lower = {c: str(c).lower() for c in columns}
    for kw in keywords:
        for col, low in col_lower.items():
            if kw in low:
                return col
    return None


def _cell_col_disambiguation_score(col: str) -> int:
    """Higher = better candidate for the human / inventory cell label."""
    low = str(col).lower()
    score = 0
    if any(x in low for x in ('lncel name', 'wcel name', 'nrcel name', 'cell_name', 'cell name')):
        score += 24
    if ' name' in low or low.endswith('name'):
        score += 10
    if low in ('dn', 'distinguished name') or 'distinguished' in low:
        score += 14
    if any(x in low for x in ('plmn name', 'rnc name', 'mrbts name', 'lnbts name', 'nrbts name')):
        score -= 8
    if low.endswith(' id') or re.search(r'\bid\b', low):
        score -= 20
    return score


def _detect_cell_identifier_column(columns, keywords):
    """
    Like ``_detect_col`` but, for each keyword, chooses the best-scoring column among
    all matches (e.g. skip ``WCEL ID`` when ``wcel`` matches both id and name columns).
    """
    col_lower = {c: str(c).lower() for c in columns}
    for kw in keywords:
        matches = []
        for col in columns:
            low = col_lower[col]
            if kw not in low:
                continue
            if kw in ('wcel', 'lncel', 'nrcel') and (low.endswith('id') or low.endswith(' id')):
                continue
            if kw == 'bts' and any(x in low for x in ('mrbts', 'lnbts', 'nrbts')):
                continue
            matches.append(col)
        if not matches:
            continue
        matches.sort(key=lambda c: (-_cell_col_disambiguation_score(c), len(str(c))))
        return matches[0]
    return None


def _pm_ids_only_column(df, col_name: str) -> bool:
    """True when the column looks like numeric IDs (wrong pick for cell_name)."""
    if not col_name or col_name not in df.columns:
        return False
    sample = df[col_name].dropna().head(100)
    if len(sample) < 5:
        return False
    bad = 0
    for v in sample:
        t = str(v).strip()
        if not t or t.lower() == 'nan':
            continue
        if t.isdigit() and len(t) <= 10:
            bad += 1
        elif len(t) <= 2:
            bad += 1
    return bad >= max(5, int(0.45 * len(sample)))


def _short_cell_label_from_dn(val: object) -> str:
    """First ``CN=`` fragment from a Nokia DN, else the stripped string."""
    s = str(val or '').strip()
    if not s or s.lower() == 'nan':
        return ''
    m = re.search(r'CN=([^,+]+)', s, flags=re.I)
    if m:
        return m.group(1).strip()
    return s


# Some Nokia/CSV exports append " DST" / " STD"; pandas treats them as TZ tokens,
# logs FutureWarning, and will raise in a future version. We keep naive wall time.
_PSEUDO_TZ_SUFFIX_RE = re.compile(r'\s+(DST|STD)\s*$', re.IGNORECASE)


def _strip_pseudo_tz_suffix(s: str) -> str:
    return _PSEUDO_TZ_SUFFIX_RE.sub('', s).strip()


def _coerce_pm_timestamp(raw_ts):
    """
    Normalise a PM time cell to 'YYYY-MM-DD HH:MM:SS' or None if unusable.
    Rejects Unix epoch / pre-2000 parses (common when the wrong column was chosen).
    """
    if raw_ts is None:
        return None
    try:
        if raw_ts is pd.NaT:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(raw_ts, float) and pd.isna(raw_ts):
        return None

    # Excel serial day number (Huawei / NetAct exports)
    if isinstance(raw_ts, (int, float)) and not isinstance(raw_ts, bool):
        x = float(raw_ts)
        if 20000 < x < 80000:
            base = datetime(1899, 12, 30)
            t = base + timedelta(days=x)
            if t.year >= 1990:
                return t.replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')

    if isinstance(raw_ts, pd.Timestamp):
        if pd.isna(raw_ts) or raw_ts.year < 2000:
            return None
        return raw_ts.strftime('%Y-%m-%d %H:%M:%S')

    s = str(raw_ts).strip()
    if not s or s.lower() in ('nan', 'nat', 'none', ''):
        return None
    s = _strip_pseudo_tz_suffix(s)
    if not s:
        return None

    # Slash dates (Huawei PRS / regional CSV: yyyy/mm/dd or dd/mm/yyyy)
    if '/' in s and len(s) >= 8:
        for dayfirst in (True, False):
            t = pd.to_datetime(s, errors='coerce', dayfirst=dayfirst)
            if not pd.isna(t) and t.year >= 2000:
                return t.replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')

    # ISO-style dates (avoid dayfirst=True ambiguity / warnings)
    if len(s) >= 10 and s[4] == '-' and s[7] == '-' and s[:4].isdigit():
        t = pd.to_datetime(s, errors='coerce')
        if not pd.isna(t) and t.year >= 2000:
            return t.strftime('%Y-%m-%d %H:%M:%S')

    # Compact numeric datetime strings (CSV floats may appear as "20260519.0")
    compact = s.split('.', 1)[0] if re.fullmatch(r'\d+\.0+', s) else s
    if compact.isdigit() and len(compact) >= 8:
        fmt = {
            8: '%Y%m%d',
            10: '%Y%m%d%H',
            12: '%Y%m%d%H%M',
            14: '%Y%m%d%H%M%S',
        }.get(len(compact))
        if fmt:
            t = pd.to_datetime(compact, format=fmt, errors='coerce')
            if not pd.isna(t) and t.year >= 2000:
                return t.strftime('%Y-%m-%d %H:%M:%S')

    # Dotted datetime seen in Nokia exports (month-first or day-first)
    if '.' in s and len(s) >= 10:
        for fmt in (
            '%m.%d.%Y %H:%M:%S',
            '%m.%d.%Y %H:%M',
            '%m.%d.%Y',
            '%d.%m.%Y %H:%M:%S',
            '%d.%m.%Y %H:%M',
            '%d.%m.%Y',
        ):
            t = pd.to_datetime(s, format=fmt, errors='coerce')
            if not pd.isna(t) and t.year >= 2000:
                return t.strftime('%Y-%m-%d %H:%M:%S')

    # Last resort: day-first only for slash/dotted dates; avoids dayfirst vs YYYYMMDD warnings
    if '/' in s:
        t = pd.to_datetime(s, errors='coerce', dayfirst=True)
        if pd.isna(t):
            t = pd.to_datetime(s, errors='coerce', dayfirst=False)
    else:
        t = pd.to_datetime(s, errors='coerce', dayfirst=False)
        if pd.isna(t) and '.' in s:
            t = pd.to_datetime(s, errors='coerce', dayfirst=True)
    if pd.isna(t) or t.year < 2000:
        return None
    return t.strftime('%Y-%m-%d %H:%M:%S')


def _pick_best_timestamp_column(df, cols):
    """
    Among columns whose names look like a time axis, pick the one whose values
    most often coerce to a real calendar time (year >= 2000).
    """
    col_lower = {c: str(c).lower() for c in cols}
    candidates = [c for c in cols if any(kw in col_lower[c] for kw in _TS_KEYWORDS)]
    if not candidates:
        return _detect_col(cols, _TS_KEYWORDS)

    best_col, best_n = None, -1
    for c in candidates:
        n_ok = 0
        try:
            for v in df[c].dropna().head(600):
                if _coerce_pm_timestamp(v) is not None:
                    n_ok += 1
        except Exception:
            continue
        if n_ok > best_n:
            best_n, best_col = n_ok, c

    if best_n > 0:
        return best_col

    return _detect_col(cols, _TS_KEYWORDS) or (candidates[0] if candidates else None)


def _resolve_key_cols(df):
    """
    Return (cell_name_col, timestamp_col).
    Falls back to column index 0 / 1 if auto-detect finds nothing.
    """
    cols = list(df.columns)
    cn = _detect_cell_identifier_column(cols, _CELL_KEYWORDS)
    if cn and _pm_ids_only_column(df, cn) and 'DN' in cols:
        cn = 'DN'
    ts = _pick_best_timestamp_column(df, cols)

    if cn is None:
        cn = cols[0]
        logger.warning(f'cell_name not detected — using first column: {cn!r}')
    if ts is None and len(cols) > 1:
        ts = cols[1]
        logger.warning(f'timestamp not detected — using second column: {ts!r}')
    elif ts is None:
        ts = cn

    return cn, ts


# ---------------------------------------------------------------------------
# Helpers: dynamic schema + insert
# ---------------------------------------------------------------------------

def _ensure_columns(conn, table, cols):
    existing = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    if not existing:
        col_defs = ['"cell_name" TEXT', '"timestamp" TEXT'] + [
            f'"{c}" REAL' for c in cols
        ]
        conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" ('
            + ', '.join(col_defs)
            + ', UNIQUE (cell_name, timestamp) ON CONFLICT REPLACE)'
        )
        return
    for col in cols:
        if col not in existing:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" REAL')


def _pm_index_suffix(table: str) -> str:
    """Stable fragment for index names (unique per table in the DB file)."""
    return ''.join(c if c.isalnum() else '_' for c in str(table))[:48]


def _ensure_pm_cell_timestamp_index_sqlite(conn, table: str) -> None:
    """Index for trend queries on vendor-native or normalized cell/time columns."""
    try:
        from core.pm_indexes import ensure_table_indexes

        ensure_table_indexes(conn, table)
    except Exception:
        try:
            suf = _pm_index_suffix(table)
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_pm_{suf}_ct" ON "{table}" (cell_name, timestamp)'
            )
        except sqlite3.OperationalError:
            pass


def _coerce_kpi_cell_value(val):
    """Match prior iterrows() behaviour: NULL / NaN → None, else float or stripped str."""
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return str(val).strip()


def _insert_df(db_path, df, technology):
    """
    Insert rows into area-partitioned technology tables (e.g. ``4G_CELLS_HOURLY__WEST_AMMAN``).
    df must have 'cell_name' and 'timestamp' columns.
    All other columns stored as-is with their original names.
    Returns (inserted, skipped).
    """
    from core.site_area import build_cell_area_index, pm_area_table_name, resolve_cell_area

    base_table = pm_table_name(technology)
    kpi_cols = [
        c for c in df.columns
        if c not in ('cell_name', 'timestamp') and c not in _DUPLICATE_KPI_NAMES
    ]
    cell_index = build_cell_area_index()

    conn = sqlite3.connect(db_path, timeout=120)
    try:
        conn.execute('PRAGMA busy_timeout=120000')  # ms — parallel RAT ingests share one DB file
    except sqlite3.Error:
        pass
    conn.execute('PRAGMA journal_mode=WAL')   # allow readers while writing
    # Faster bulk ingest while keeping durability reasonable for periodic PM loads.
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA temp_store=MEMORY')

    inserted = 0
    skipped = 0
    col_names = ['cell_name', 'timestamp'] + kpi_cols
    quoted_cols = ', '.join(f'"{c}"' for c in col_names)
    placeholders = ', '.join(['?'] * len(col_names))

    cell_arr = df['cell_name'].to_numpy()
    ts_arr = df['timestamp'].to_numpy()
    kpi_arrs = [df[c].to_numpy(copy=False) for c in kpi_cols]
    n = len(df)

    batches: dict[str, list[tuple]] = {}
    ensured: set[str] = set()

    for i in range(n):
        cell_name = str(cell_arr[i]).strip()
        if not cell_name or cell_name == 'nan':
            skipped += 1
            continue

        ts = _coerce_pm_timestamp(ts_arr[i])
        if ts is None:
            skipped += 1
            continue

        area = resolve_cell_area(cell_name, cell_index=cell_index)
        table = pm_area_table_name(base_table, area)
        if table not in ensured:
            _ensure_columns(conn, table, kpi_cols)
            ensured.add(table)

        row_vals: list = [None] * len(col_names)
        row_vals[0] = cell_name
        row_vals[1] = ts
        for j, col in enumerate(kpi_cols):
            row_vals[2 + j] = _coerce_kpi_cell_value(kpi_arrs[j][i])

        batches.setdefault(table, []).append(tuple(row_vals))
        inserted += 1

        if len(batches[table]) >= PM_INSERT_BATCH_SIZE:
            sql = f'INSERT OR REPLACE INTO "{table}" ({quoted_cols}) VALUES ({placeholders})'
            conn.executemany(sql, batches[table])
            batches[table].clear()

    for table, batch in batches.items():
        if not batch:
            continue
        sql = f'INSERT OR REPLACE INTO "{table}" ({quoted_cols}) VALUES ({placeholders})'
        conn.executemany(sql, batch)
        _ensure_pm_cell_timestamp_index_sqlite(conn, table)

    for table in ensured:
        _ensure_pm_cell_timestamp_index_sqlite(conn, table)

    conn.commit()
    conn.close()
    logger.info(
        f'[{technology}] {db_path} → {base_table} partitions: {inserted} inserted, {skipped} skipped.'
    )
    return inserted, skipped


def apply_pm_retention(db_path: str, days: int) -> None:
    """Delete rows older than ``days`` using vendor-aware timestamp columns (canonical tables)."""
    if days <= 0:
        return
    from core.pm_retention import apply_retention

    low = db_path.replace("\\", "/").lower()
    if "huawei" in low:
        label = "huawei-groups" if "groups" in low else "huawei-cells"
    elif "nokia" in low:
        label = "nokia-groups" if "groups" in low else "nokia-cells"
    else:
        label = "pm-cells"
    deleted = apply_retention(db_path, days, label)
    logger.info(
        "PM retention SQLite %s: removed ~%s rows older than %s days.",
        db_path,
        deleted,
        days,
    )


# ---------------------------------------------------------------------------
# Nokia: one file per technology
# ---------------------------------------------------------------------------

def clear_nokia_pm_tables():
    logger.info('PM reset mode: clear_nokia_pm_tables disabled.')
    return
    """Remove all Nokia PM rows before a new pull."""
    tables = [pm_table_name(t) for t in PM_TECHNOLOGIES]

    conn = sqlite3.connect(NOKIA_PM_DB, timeout=30)
    cleared = 0
    for table in tables:
        try:
            conn.execute(f'DELETE FROM "{table}"')
            cleared += 1
        except sqlite3.OperationalError:
            continue
    conn.commit()
    conn.close()
    logger.info('Nokia PM: cleared %s table(s) in SQLite file.', cleared)

def process_nokia_pm_file(file_path, technology):
    logger.info('PM reset mode: process_nokia_pm_file disabled (%s, %s).', technology, file_path)
    return 0, 0, 'PM ingest disabled (reset mode)'
    """
    Process a Nokia PM file (XLSX, XLS, or CSV).
    Auto-detects cell_name and timestamp columns.
    Returns (inserted, skipped, error_message).
    """
    ext0 = os.path.splitext(file_path)[1].lower()
    if ext0 == '.zip':
        tmp_dir = tempfile.mkdtemp(prefix='nokia_pm_zip_')
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                zf.extractall(tmp_dir)
            candidates = []
            for root, _, files in os.walk(tmp_dir):
                for fn in files:
                    low = fn.lower()
                    if low.endswith(('.xlsx', '.xls', '.xlsm', '.csv')):
                        full = os.path.join(root, fn)
                        prio = 0 if low.endswith(('.xlsx', '.xls', '.xlsm')) else 1
                        candidates.append((prio, os.path.getmtime(full), full))
            if not candidates:
                err = f'ZIP has no supported files (.xlsx/.xls/.xlsm/.csv): {file_path}'
                logger.error(err)
                return 0, 0, err
            candidates.sort(key=lambda x: (x[0], -x[1]))
            chosen = candidates[0][2]
            logger.info('Nokia PM [%s] ZIP selected file: %s', technology, chosen)
            return process_nokia_pm_file(chosen, technology)
        except Exception as e:
            return 0, 0, str(e)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ('.csv', '.txt'):
            df = _read_nokia_csv_best(file_path)
            if df is None or df.empty or len(df.columns) < 2:
                df = _load_pm_file(file_path)
        else:
            df = _load_pm_file(file_path)
    except Exception as e:
        logger.error(f'Failed to read Nokia PM file {file_path}: {e}')
        return 0, 0, str(e)

    cn_col, ts_col = _resolve_key_cols(df)
    logger.info(f'Nokia PM [{technology}]: cell_name={cn_col!r}, timestamp={ts_col!r}')

    rename = {}
    if cn_col != 'cell_name':
        rename[cn_col] = 'cell_name'
    if ts_col != 'timestamp' and ts_col != cn_col:
        rename[ts_col] = 'timestamp'
    df = df.rename(columns=rename)

    if 'cell_name' not in df.columns:
        df = df.rename(columns={df.columns[0]: 'cell_name'})
    if 'timestamp' not in df.columns:
        df['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if str(cn_col).strip().lower() == 'dn':
        df['cell_name'] = df['cell_name'].map(_short_cell_label_from_dn)

    inserted, skipped = _insert_df(NOKIA_PM_DB, df, technology)
    return inserted, skipped, None


def run_nokia_pm_sync(downloaded_files, column_maps=None):
    del column_maps
    summary: dict = {}
    for tech in (downloaded_files or {}):
        summary[tech] = {'status': 'skipped', 'reason': 'PM ingest disabled (reset mode)'}
    return summary
    """
    downloaded_files = {technology: local_path or None}
    column_maps is accepted but ignored (kept for call-site compatibility).

    Ingests **all technologies in parallel** (separate threads, each writing its
    own hourly table in the same SQLite DB). Set ``PM_INGEST_PARALLEL_WORKERS``
    to cap threads (default 5).
    """
    summary: dict = {}
    pending: list[tuple[str, str]] = []
    for tech, file_path in downloaded_files.items():
        if not file_path:
            summary[tech] = {'status': 'skipped', 'reason': 'Download failed or not configured'}
            continue
        pending.append((tech, file_path))

    if not pending:
        return summary

    def _one_nokia(tech: str, path: str):
        return process_nokia_pm_file(path, tech)

    if len(pending) == 1:
        tech, fp = pending[0]
        inserted, skipped, error = _one_nokia(tech, fp)
        summary[tech] = (
            {'status': 'error', 'error': error}
            if error
            else {'status': 'ok', 'inserted': inserted, 'skipped': skipped}
        )
        return summary

    tasks = [(tech, partial(_one_nokia, tech, fp)) for tech, fp in pending]
    raw = _parallel_pm_zeroarg_tasks(tasks, max_workers=_PM_PARALLEL_CAP)
    for tech, fp in pending:
        res = raw.get(tech)
        if isinstance(res, Exception):
            summary[tech] = {'status': 'error', 'error': str(res)}
            continue
        inserted, skipped, error = res
        summary[tech] = (
            {'status': 'error', 'error': error}
            if error
            else {'status': 'ok', 'inserted': inserted, 'skipped': skipped}
        )
    return summary


# ---------------------------------------------------------------------------
# Local directory PM ingest (manual / tool-assisted)
# ---------------------------------------------------------------------------

def _infer_pm_vendor(file_path: str) -> str | None:
    """Infer PM vendor from path/name; returns 'Nokia', 'Huawei', or None."""
    low = str(file_path).replace('\\', '/').lower()
    base = os.path.basename(low)
    if any(x in low for x in ('/pm_huawei/', '/huawei/', 'huawei_')) or 'huawei' in base:
        return 'Huawei'
    if any(x in low for x in ('/pm_nokia/', '/nokia/', 'nokia_')) or 'nokia' in base:
        return 'Nokia'
    return None


def _infer_pm_technology(file_path: str) -> str:
    """Infer PM technology from file name/path; defaults to 4G when ambiguous."""
    low = str(file_path).lower()
    if any(x in low for x in ('5g', 'nr', 'nrcel')):
        return '5G'
    if any(x in low for x in ('4g', 'lte', 'lncel', 'fdd', 'tdd')):
        return '4G'
    if any(x in low for x in ('3g', 'wcdma', 'umts', 'wcel')):
        return '3G'
    if any(x in low for x in ('2g', 'gsm', 'gprs', 'edge', 'bts')):
        return '2G'
    return '4G'


def _collect_pm_files(root_dir: str, recursive: bool = True) -> list[str]:
    exts = ('.xlsx', '.xls', '.xlsm', '.csv', '.zip')
    out: list[str] = []
    if recursive:
        for root, _, files in os.walk(root_dir):
            for fn in files:
                full = os.path.join(root, fn)
                if os.path.isfile(full) and full.lower().endswith(exts):
                    out.append(full)
    else:
        for fn in os.listdir(root_dir):
            full = os.path.join(root_dir, fn)
            if os.path.isfile(full) and full.lower().endswith(exts):
                out.append(full)
    out.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return out


def import_pm_from_directory(root_dir: str, vendor: str = 'all', recursive: bool = True) -> dict:
    del recursive
    return {
        'status': 'error',
        'path': root_dir,
        'vendor': vendor,
        'error': 'PM local import disabled (reset mode)',
    }
    """
    Import all PM files found under ``root_dir``.
    Vendor can be: all | nokia | huawei.
    """
    if not root_dir or not os.path.isdir(root_dir):
        return {'status': 'error', 'error': f'Invalid path: {root_dir!r}'}

    want = (vendor or 'all').strip().lower()
    if want not in ('all', 'nokia', 'huawei'):
        return {'status': 'error', 'error': 'vendor must be one of: all, nokia, huawei'}

    files = _collect_pm_files(root_dir, recursive=recursive)
    if not files:
        return {'status': 'ok', 'path': root_dir, 'vendor': want, 'files': 0, 'inserted': 0, 'skipped': 0, 'results': []}

    total_inserted = 0
    total_skipped = 0
    results: list[dict] = []
    for p in files:
        detected_vendor = _infer_pm_vendor(p)
        if want == 'nokia':
            file_vendor = 'Nokia'
        elif want == 'huawei':
            file_vendor = 'Huawei'
        else:
            file_vendor = detected_vendor
            if file_vendor is None:
                results.append({'file': p, 'status': 'skipped', 'reason': 'Could not infer vendor; include nokia/huawei in path or filename.'})
                continue

        tech = _infer_pm_technology(p)
        try:
            if file_vendor == 'Nokia':
                ins, skip, err = process_nokia_pm_file(p, tech)
                if err:
                    results.append({'file': p, 'vendor': file_vendor, 'technology': tech, 'status': 'error', 'error': err})
                else:
                    total_inserted += int(ins or 0)
                    total_skipped += int(skip or 0)
                    results.append({'file': p, 'vendor': file_vendor, 'technology': tech, 'status': 'ok', 'inserted': ins, 'skipped': skip})
            else:
                summary = process_huawei_pm_file(p, default_technology=tech)
                file_inserted = 0
                file_skipped = 0
                any_ok = False
                errs = []
                for _, r in summary.items():
                    if r.get('status') == 'ok':
                        any_ok = True
                        file_inserted += int(r.get('inserted', 0) or 0)
                        file_skipped += int(r.get('skipped', 0) or 0)
                    elif r.get('status') == 'error':
                        errs.append(r.get('error') or 'unknown error')
                total_inserted += file_inserted
                total_skipped += file_skipped
                if any_ok:
                    results.append({'file': p, 'vendor': file_vendor, 'technology': tech, 'status': 'ok', 'inserted': file_inserted, 'skipped': file_skipped})
                else:
                    results.append({'file': p, 'vendor': file_vendor, 'technology': tech, 'status': 'error', 'error': '; '.join(e for e in errs if e) or 'No rows inserted'})
        except Exception as e:
            results.append({'file': p, 'vendor': file_vendor, 'technology': tech, 'status': 'error', 'error': str(e)})

    return {
        'status': 'ok',
        'path': root_dir,
        'vendor': want,
        'files': len(files),
        'inserted': total_inserted,
        'skipped': total_skipped,
        'results': results,
    }


# ---------------------------------------------------------------------------
# Huawei PM — same hourly tables as Nokia (2G_Hourly … 5G_Hourly in HUAWEI_PM_DB)
# ---------------------------------------------------------------------------


def _infer_huawei_technology_from_label(label: str, index: int = 0) -> str:
    """
    Map filename / sheet name to a PM_TECHNOLOGIES key.
    If the name is ambiguous, use ``index`` (0 → 2G, 1 → 3G, …) like ordered CSVs in a zip.
    """
    u = (label or '').lower()
    if any(x in u for x in ('5g', 'nr', 'nrcel')):
        return '5G'
    if any(x in u for x in ('4g', 'lte', 'eutran', 'lncel')):
        return '4G'
    if any(x in u for x in ('3g', 'wcdma', 'umts', 'wcel')):
        return '3G'
    if any(x in u for x in ('2g', 'gsm', 'gprs', 'edge', 'bts')):
        return '2G'
    return PM_TECHNOLOGIES[min(index, len(PM_TECHNOLOGIES) - 1)]


def _huawei_read_tabular(path: str) -> pd.DataFrame:
    """Same read path as Nokia PM (CSV fast-path, then generic loader)."""
    tr = _huawei_pm_debug()
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.csv', '.txt', '.tsv', '.dat'):
        df = _read_nokia_csv_best(path)
        if df is not None and not df.empty and len(df.columns) >= 2:
            _huawei_pm_trace(
                'read %s: _read_nokia_csv_best ok rows=%s cols=%s sample_headers=%s',
                os.path.basename(path),
                len(df),
                len(df.columns),
                list(df.columns)[:12],
            )
        else:
            _huawei_pm_trace(
                'read %s: _read_nokia_csv_best weak/empty (df=%s) → _load_pm_file',
                os.path.basename(path),
                'None' if df is None else f'rows={len(df)} cols={len(df.columns)}',
            )
            df = _load_pm_file(path, trace=tr)
    else:
        _huawei_pm_trace('read %s: non-csv extension → _load_pm_file', os.path.basename(path))
        df = _load_pm_file(path, trace=tr)
    return df


def _literal_date_column_for_timestamp(df: pd.DataFrame, ts_col) -> object:
    """
    Huawei PRS CSV often has a ``Date`` column (dd/mm/yyyy). Prefer it over a
    generic ``time`` KPI column that can coerce to 1970 and cause all rows to be skipped.
    """
    for c in df.columns:
        if str(c).strip().lower() != 'date':
            continue
        if c == ts_col:
            return ts_col
        sample = df[c].dropna().head(500)
        if len(sample) < 1:
            continue
        ok = sum(1 for v in sample if _coerce_pm_timestamp(v) is not None)
        if ok >= max(3, int(0.75 * len(sample))):
            return c
    return ts_col


def _prepare_pm_df_like_nokia(df: pd.DataFrame, log_tag: str) -> tuple[pd.DataFrame | None, str | None]:
    """Normalize columns to cell_name + timestamp (Nokia PM rules)."""
    if df is None or df.empty or len(df.columns) < 2:
        return None, 'empty or too few columns'
    df = df.copy()
    df.columns = [str(c).strip().lstrip('\ufeff') for c in df.columns]
    cn_col, ts_col = _resolve_key_cols(df)
    ts_col = _literal_date_column_for_timestamp(df, ts_col)
    logger.info('%s: cell_name=%r, timestamp=%r', log_tag, cn_col, ts_col)
    rename: dict = {}
    if cn_col != 'cell_name':
        rename[cn_col] = 'cell_name'
    if ts_col != 'timestamp' and ts_col != cn_col:
        rename[ts_col] = 'timestamp'
    df = df.rename(columns=rename)
    if 'cell_name' not in df.columns:
        df = df.rename(columns={df.columns[0]: 'cell_name'})
    if 'timestamp' not in df.columns:
        df['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if str(cn_col).strip().lower() == 'dn':
        df['cell_name'] = df['cell_name'].map(_short_cell_label_from_dn)
    return df, None


_TABULAR_EXTS = ('.csv', '.txt', '.tsv', '.dat')


def _huawei_zip_tabular_candidates(extracted_root: str) -> list[str]:
    """Every tabular file path under ``extracted_root`` (no size limit)."""
    paths: list[str] = []
    for walk_root, _, files in os.walk(extracted_root):
        for fn in files:
            low = fn.lower()
            if not low.endswith(_TABULAR_EXTS):
                continue
            if fn.startswith('._'):
                continue
            full = os.path.join(walk_root, fn)
            if not os.path.isfile(full):
                continue
            if any(k in low for k in ('readme', 'changelog', 'manifest', 'license')):
                continue
            paths.append(full)
    return paths


def _huawei_zip_tabular_paths(extracted_root: str, max_files: int = 5, trace: bool = False) -> list[str]:
    """Plausible PM tabular files in an extracted tree (PRS often uses .txt/.tsv/.dat, not only .csv)."""
    paths = _huawei_zip_tabular_candidates(extracted_root)
    if trace:
        _huawei_pm_trace('tabular files under extract root: %s match(es)', len(paths))
        ranked = sorted(paths, key=lambda p: (-os.path.getsize(p), os.path.basename(p).lower()))
        for p in ranked:
            _huawei_pm_trace(
                '  candidate %s bytes=%s',
                os.path.relpath(p, extracted_root).replace('\\', '/'),
                os.path.getsize(p),
            )
    if not paths:
        return []
    if len(paths) <= max_files:
        paths.sort(key=lambda p: os.path.basename(p).lower())
        if trace:
            for p in paths:
                _huawei_pm_trace('  selected (all fit, sorted by name): %s', os.path.relpath(p, extracted_root))
        return paths
    paths.sort(key=lambda p: (-os.path.getsize(p), os.path.basename(p).lower()))
    sel = paths[:max_files]
    if trace:
        _huawei_pm_trace(
            '  selected top %s by file size (%s tabular files total):',
            max_files,
            len(paths),
        )
        for p in sel:
            _huawei_pm_trace('    %s', os.path.relpath(p, extracted_root))
    return sel


def _clear_huawei_pm_tables():
    """Delete all rows from fixed RAT tables (same layout as Nokia PM)."""
    tables = [pm_table_name(t) for t in PM_TECHNOLOGIES]
    conn = sqlite3.connect(HUAWEI_PM_DB, timeout=30)
    cleared = 0
    for table in tables:
        try:
            conn.execute(f'DELETE FROM "{table}"')
            cleared += 1
        except sqlite3.OperationalError:
            continue
    conn.commit()
    conn.close()
    logger.info('Huawei PM: cleared %s table(s) in SQLite file.', cleared)


def clear_huawei_pm_tables():
    """Public wrapper — disabled in reset mode."""
    logger.info('PM reset mode: clear_huawei_pm_tables disabled.')
    return


def _clear_huawei_pm_tables_if_full_sync():
    """Disabled in reset mode."""
    logger.info('PM reset mode: _clear_huawei_pm_tables_if_full_sync disabled.')
    return


def huawei_pm_user_tables(db_path: str | None = None) -> list[str]:
    return [pm_table_name(t) for t in PM_TECHNOLOGIES]


def huawei_pm_kpi_tables(db_path: str | None = None) -> list[str]:
    """RAT tables including area partitions when present in the DB."""
    path = HUAWEI_PM_DB if db_path is None else db_path
    scope = 'daily' if 'daily' in os.path.normpath(str(path or '')).replace('\\', '/').lower() else 'hourly'
    bases = [pm_table_name(t, scope) for t in PM_TECHNOLOGIES]
    if not path or not os.path.isfile(path):
        return bases
    try:
        conn = sqlite3.connect(path, timeout=15)
        try:
            names = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
        finally:
            conn.close()
    except sqlite3.Error:
        return bases
    from core.site_area import list_pm_partition_tables

    out: list[str] = []
    for base in bases:
        parts = list_pm_partition_tables(names, base)
        if parts:
            out.extend(parts)
            continue
        # Fall back to any existing cells table for this RAT (name drift).
        tech = base.split('_', 1)[0]
        matched = [n for n in names if n.upper().startswith(f'{tech}_CELLS')]
        out.extend(matched or [base])
    return out


def huawei_table_matches_technology(table: str, technology: str | None) -> bool:
    """When ``technology`` is None/empty, all tables match."""
    if not technology:
        return True
    tech = technology.strip().upper()
    t = table.upper()
    for scope in ('hourly', 'daily'):
        legacy = pm_table_name(technology, scope)
        if table == legacy or t == legacy.upper() or t.startswith(legacy.upper() + "__"):
            return True
    if tech in t:
        return True
    if tech == '4G':
        return any(x in t for x in ('4G', 'LTE', 'FDD', 'TDD', 'EUTRAN'))
    if tech == '5G':
        return any(x in t for x in ('5G', 'NR', 'G5'))
    if tech == '3G':
        return any(x in t for x in ('3G', 'WCDMA', 'UMTS'))
    if tech == '2G':
        return any(x in t for x in ('2G', 'GSM', 'GPRS', 'EDGE'))
    return False


def huawei_pm_table_for_cell(
    cell_name: str,
    cell_technology: str | None = None,
    db_path: str | None = None,
) -> str | None:
    """Pick the PM table for this cell (prefer area partition, then base)."""
    from core.site_area import list_pm_partition_tables, pm_area_table_name, resolve_cell_area

    path = HUAWEI_PM_DB if db_path is None else db_path
    scope = 'daily' if 'daily' in os.path.normpath(str(path or '')).replace('\\', '/').lower() else 'hourly'
    base = pm_table_name(cell_technology or '4G', scope)
    preferred = pm_area_table_name(base, resolve_cell_area(cell_name))
    probe_order = [preferred, base]
    names: list[str] = []

    conn = sqlite3.connect(path, timeout=15)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for base_cand in [base] + [
            pm_table_name(t, scope) for t in PM_TECHNOLOGIES if pm_table_name(t, scope) != base
        ]:
            for tbl in list_pm_partition_tables(names, base_cand):
                if tbl not in probe_order:
                    probe_order.append(tbl)
            if base_cand in names and base_cand not in probe_order:
                probe_order.append(base_cand)

        for tbl in probe_order:
            if tbl not in names:
                continue
            try:
                if conn.execute(
                    f'SELECT 1 FROM "{tbl}" WHERE cell_name = ? LIMIT 1',
                    (cell_name,),
                ).fetchone():
                    return tbl
            except sqlite3.OperationalError:
                pass
            try:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()]
            except sqlite3.OperationalError:
                continue
            for cand in ('Cell Name', 'LNCEL name', 'WCEL name', 'NRCEL name', 'BTS name'):
                if cand not in cols:
                    continue
                try:
                    if conn.execute(
                        f'SELECT 1 FROM "{tbl}" WHERE "{cand}" = ? LIMIT 1',
                        (cell_name,),
                    ).fetchone():
                        return tbl
                except sqlite3.OperationalError:
                    continue
    finally:
        conn.close()
    if preferred in names:
        return preferred
    if base in names:
        return base
    return preferred


def resolve_huawei_pm_table(technology: str, db_path: str | None = None) -> str | None:
    """Map UI technology to the Huawei PM table name (hourly or daily from db path)."""
    path = db_path or HUAWEI_PM_DB
    scope = 'daily' if 'daily' in os.path.normpath(str(path)).replace('\\', '/').lower() else 'hourly'
    return pm_table_name(technology or '4G', scope)


def _huawei_ingest_prepared_df(prep: pd.DataFrame, technology: str) -> dict:
    try:
        ins, skip = _insert_df(HUAWEI_PM_DB, prep, technology)
        n = len(prep)
        if ins == 0 and n > 0 and skip >= n:
            msg = (
                f'no rows inserted ({skip}/{n} skipped: invalid timestamp or empty cell_name); '
                f'check CSV time and cell columns'
            )
            logger.error('Huawei PM [%s]: %s', technology, msg)
            return {
                'status': 'error',
                'error': msg,
                'inserted': 0,
                'skipped': skip,
                'table': pm_table_name(technology),
            }
        return {
            'status': 'ok',
            'inserted': ins,
            'skipped': skip,
            'table': pm_table_name(technology),
        }
    except Exception as e:
        logger.exception('Huawei PM insert failed technology=%s', technology)
        return {'status': 'error', 'error': str(e)}


def debug_huawei_pm_zip(file_path: str) -> dict:
    """
    Inspect a Huawei ``Performance.zip`` (or similar) **without writing the PM database**:
    archive members, which tabular files are selected, read dimensions, and ``_prepare_pm_df_like_nokia`` outcome.

    Intended for CLI / support: ``python scripts/debug_huawei_pm_zip.py <zip>``
    """
    out: dict = {'zip_path': os.path.abspath(file_path), 'members': [], 'tabular_candidates': 0, 'tabular_selected': [], 'per_file': []}
    if not os.path.isfile(file_path):
        out['error'] = 'not a file'
        return out
    with zipfile.ZipFile(file_path, 'r') as zf:
        for zi in zf.infolist():
            if zi.is_dir():
                continue
            out['members'].append({'name': zi.filename.replace('\\', '/'), 'size': zi.file_size})
    tmp_dir = tempfile.mkdtemp(prefix='huawei_pm_debug_')
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            zf.extractall(tmp_dir)
        cands = _huawei_zip_tabular_candidates(tmp_dir)
        out['tabular_candidates'] = len(cands)
        tabular_paths = _huawei_zip_tabular_paths(tmp_dir, max_files=5, trace=False)
        out['tabular_selected'] = [os.path.relpath(p, tmp_dir).replace('\\', '/') for p in tabular_paths]
        dt = None
        for i, cp in enumerate(tabular_paths):
            label = os.path.splitext(os.path.basename(cp))[0] or 'file'
            tech = dt or _infer_huawei_technology_from_label(label, i)
            entry: dict = {
                'label': label,
                'technology': tech,
                'relative_path': os.path.relpath(cp, tmp_dir).replace('\\', '/'),
                'size_bytes': os.path.getsize(cp),
            }
            try:
                nb = _read_nokia_csv_best(cp)
                if nb is not None and not nb.empty:
                    entry['nokia_csv_best'] = {
                        'rows': len(nb),
                        'cols': len(nb.columns),
                        'headers': [str(x) for x in nb.columns[:25]],
                    }
                else:
                    entry['nokia_csv_best'] = None
                raw = _huawei_read_tabular(cp)
                entry['after_read'] = {
                    'rows': len(raw),
                    'cols': len(raw.columns),
                    'headers': [str(x) for x in raw.columns[:25]],
                }
                prep, perr = _prepare_pm_df_like_nokia(
                    raw,
                    f'Huawei PM ZIP [{tech}] {os.path.basename(cp)}',
                )
                entry['prepare_ok'] = prep is not None
                entry['prepare_error'] = perr
                if prep is not None:
                    entry['prepared_sample'] = {
                        'rows': len(prep),
                        'cols': len(prep.columns),
                        'headers': [str(x) for x in prep.columns[:25]],
                    }
            except Exception as e:
                entry['error'] = str(e)
            out['per_file'].append(entry)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return out


def process_huawei_pm_file(file_path, column_maps=None, sheet_tech_map=None, default_technology=None):
    del column_maps, sheet_tech_map, default_technology
    return {
        os.path.basename(file_path) or 'file': {
            'status': 'skipped',
            'reason': 'Huawei PM ingest disabled (reset mode)',
        }
    }
    """
    Ingest Huawei PM like Nokia PM: rows go into ``2G_Hourly`` … ``5G_Hourly`` in ``huawei_pm_cells.db``.

    - **ZIP** (e.g. ``Performance.zip``): extract, load each largest tabular file
      ``.csv`` / ``.txt`` / ``.tsv`` / ``.dat`` (up to 5), map to RAT by filename or zip order;
      or if there are none, ingest the largest inner workbook.
    - **Workbook**: one sheet per technology (inferred from sheet name unless ``default_technology`` is set).
    - **Single CSV / other**: one RAT from filename or ``default_technology`` or ``4G``.

    ``column_maps`` / ``sheet_tech_map`` are ignored (call-site compatibility).
    """
    del column_maps, sheet_tech_map
    dt = (default_technology or '').strip() or None

    ext0 = os.path.splitext(file_path)[1].lower()
    if ext0 == '.zip':
        tmp_dir = tempfile.mkdtemp(prefix='huawei_pm_zip_')
        try:
            dbg = _huawei_pm_debug()
            with zipfile.ZipFile(file_path, 'r') as zf:
                if dbg:
                    infos = [zi for zi in zf.infolist() if not zi.is_dir()]
                    _huawei_pm_trace(
                        'opening ZIP %s — %s stored file(s) (showing up to 60)',
                        os.path.basename(file_path),
                        len(infos),
                    )
                    for zi in sorted(infos, key=lambda z: z.filename.lower())[:60]:
                        _huawei_pm_trace(
                            '  zip member: %s (%s bytes)',
                            zi.filename.replace('\\', '/'),
                            zi.file_size,
                        )
                    if len(infos) > 60:
                        _huawei_pm_trace('  ... %s more member(s)', len(infos) - 60)
                zf.extractall(tmp_dir)
            if dbg:
                _huawei_pm_trace('extracted to temp dir: %s', tmp_dir)
            tabular_paths = _huawei_zip_tabular_paths(tmp_dir, max_files=5, trace=dbg)
            if not tabular_paths:
                xlsx_paths: list[str] = []
                for root, _, files in os.walk(tmp_dir):
                    for fn in files:
                        if fn.lower().endswith(('.xlsx', '.xls', '.xlsm')):
                            xlsx_paths.append(os.path.join(root, fn))
                if xlsx_paths:
                    xlsx_paths.sort(key=lambda p: (-os.path.getsize(p), p.lower()))
                    chosen = xlsx_paths[0]
                    logger.info('Huawei PM ZIP: no tabular text; using workbook %s', chosen)
                    return process_huawei_pm_file(chosen, default_technology=dt)
                err = (
                    f'ZIP has no tabular (.csv/.txt/.tsv/.dat) or workbook (.xlsx/.xls/.xlsm) files: {file_path}'
                )
                logger.error(err)
                return {'zip': {'status': 'error', 'error': err}}

            batch: list[tuple[str, str, pd.DataFrame]] = []
            for i, cp in enumerate(tabular_paths):
                label = os.path.splitext(os.path.basename(cp))[0] or 'csv'
                tech = dt or _infer_huawei_technology_from_label(label, i)
                if dbg:
                    _huawei_pm_trace(
                        '--- ingest %s/%s label=%r tech=%r file=%s',
                        i + 1,
                        len(tabular_paths),
                        label,
                        tech,
                        os.path.relpath(cp, tmp_dir).replace('\\', '/'),
                    )
                try:
                    raw = _huawei_read_tabular(cp)
                except Exception as e:
                    logger.exception('Huawei PM ZIP: read failed %s', cp)
                    return {label: {'status': 'error', 'error': str(e)}}
                prep, perr = _prepare_pm_df_like_nokia(
                    raw,
                    f'Huawei PM ZIP [{tech}] {os.path.basename(cp)}',
                )
                if prep is None:
                    return {label: {'status': 'error', 'error': perr or 'unreadable'}}
                batch.append((label, tech, prep))
                logger.info(
                    'Huawei PM ZIP: prepared %s rows=%s cols=%s',
                    os.path.basename(cp),
                    len(prep),
                    len(prep.columns),
                )

            _clear_huawei_pm_tables_if_full_sync()
            ingest_tasks = [
                (label, partial(_huawei_ingest_prepared_df, prep, tech))
                for label, tech, prep in batch
            ]
            summary = _parallel_pm_zeroarg_tasks(ingest_tasks, max_workers=_PM_PARALLEL_CAP)
            for lab, res in list(summary.items()):
                if isinstance(res, Exception):
                    summary[lab] = {'status': 'error', 'error': str(res)}
            return summary
        except Exception as e:
            return {'zip': {'status': 'error', 'error': str(e)}}
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    ext = os.path.splitext(file_path)[1].lower()
    xl = None
    if ext in ('.xlsx', '.xls', '.xlsm'):
        try:
            xl = pd.ExcelFile(file_path, engine='openpyxl')
        except Exception:
            try:
                xl = pd.ExcelFile(file_path, engine='xlrd')
            except Exception:
                xl = None

    if xl is not None:
        summary: dict = {}
        parsed: list[tuple[str, str, pd.DataFrame]] = []
        for i, sheet_name in enumerate(xl.sheet_names):
            try:
                df = xl.parse(sheet_name)
            except Exception as e:
                summary[sheet_name] = {'status': 'error', 'error': str(e)}
                continue
            if df is None or len(df.columns) == 0:
                summary[sheet_name] = {'status': 'skipped', 'reason': 'empty_sheet'}
                continue
            tech = dt or _infer_huawei_technology_from_label(sheet_name, i)
            prep, perr = _prepare_pm_df_like_nokia(df, f'Huawei PM sheet {sheet_name!r} → {tech}')
            if prep is None:
                summary[sheet_name] = {'status': 'error', 'error': perr or 'unreadable'}
                continue
            parsed.append((sheet_name, tech, prep))

        if not parsed:
            logger.warning('Huawei PM: workbook had no importable sheets.')
            return summary or {'workbook': {'status': 'error', 'error': 'no_importable_sheets'}}

        _clear_huawei_pm_tables_if_full_sync()
        ingest_tasks = [
            (sheet_name, partial(_huawei_ingest_prepared_df, prep, tech))
            for sheet_name, tech, prep in parsed
        ]
        summary.update(_parallel_pm_zeroarg_tasks(ingest_tasks, max_workers=_PM_PARALLEL_CAP))
        for lab, res in list(summary.items()):
            if isinstance(res, Exception):
                summary[lab] = {'status': 'error', 'error': str(res)}
        return summary

    try:
        raw = _huawei_read_tabular(file_path)
    except Exception as e:
        logger.error('Failed to read Huawei PM file %s: %s', file_path, e)
        return {'file': {'status': 'error', 'error': str(e)}}

    stem = os.path.splitext(os.path.basename(file_path))[0] or 'huawei'
    tech = dt or _infer_huawei_technology_from_label(stem, 0)
    prep, perr = _prepare_pm_df_like_nokia(raw, f'Huawei PM [{tech}] {stem}')
    if prep is None:
        return {stem: {'status': 'error', 'error': perr or 'unreadable'}}

    _clear_huawei_pm_tables_if_full_sync()
    return {stem: _huawei_ingest_prepared_df(prep, tech)}


# ---------------------------------------------------------------------------
# Legacy compat shim
# ---------------------------------------------------------------------------

def run_pm_sync(downloaded_files, column_map=None):
    """Compat shim — column_map ignored."""
    return run_nokia_pm_sync(downloaded_files)
