#!/usr/bin/env python3
"""
Header Inspector
================
Run this script ONCE from a machine that can reach the SFTP servers.
It connects to each server, downloads one sample file, and prints
every column name found — so you can update sync_config.py correctly.

Usage:
    python tools/inspect_headers.py

Output is written to tools/headers_report.txt as well as stdout.
"""

import os
import sys
import stat
import tempfile
import textwrap
from datetime import datetime

# Make sure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import paramiko
    import pandas as pd
except ImportError:
    print("ERROR: Run:  pip install paramiko openpyxl pandas")
    sys.exit(1)

from sync_config import (
    NOKIA_PM_SERVER, NOKIA_PM_COLUMN_MAPS,
    HUAWEI_PM_SERVER, HUAWEI_PM_COLUMN_MAPS, HUAWEI_SHEET_TECH_MAP,
    METADATA_SERVER, METADATA_CSV_COLUMN_MAPS, METADATA_FILE_MAP,
)

REPORT_PATH = os.path.join(os.path.dirname(__file__), 'headers_report.txt')
EXCEL_EXTS  = ('.xlsx', '.xls')

lines = []


def log(text=''):
    print(text)
    lines.append(text)


def _open_sftp(cfg):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=cfg['host'],
        port=cfg.get('port', 22),
        username=cfg['username'],
        password=cfg['password'],
        timeout=20,
    )
    return ssh, ssh.open_sftp()


def latest_xlsx(sftp, remote_dir):
    """Return (filename, remote_path) of the newest XLSX in remote_dir."""
    entries = sftp.listdir_attr(remote_dir)
    xlsx = [e for e in entries
            if not stat.S_ISDIR(e.st_mode)
            and e.filename.lower().endswith(EXCEL_EXTS)]
    if not xlsx:
        return None, None
    xlsx.sort(key=lambda e: e.st_mtime or 0, reverse=True)
    newest = xlsx[0]
    return newest.filename, f'{remote_dir.rstrip("/")}/{newest.filename}'


def download_to_tmp(sftp, remote_path, suffix='.xlsx'):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    sftp.get(remote_path, tmp.name)
    tmp.close()
    return tmp.name


def print_excel_headers(local_path, label):
    """Print sheet names and column headers for every sheet in an Excel file."""
    try:
        xl = pd.ExcelFile(local_path, engine='openpyxl')
        log(f'  Sheets found: {xl.sheet_names}')
        for sheet in xl.sheet_names:
            df = xl.parse(sheet, nrows=0)   # headers only
            cols = list(df.columns)
            log(f'  Sheet [{sheet}] — {len(cols)} columns:')
            for c in cols:
                log(f'    • {repr(c)}')
    except Exception as e:
        log(f'  ERROR reading {label}: {e}')


def print_mapping_diff(found_cols, column_map, label):
    """Show which configured header values are actually found in the file."""
    log(f'\n  --- sync_config mapping check for {label} ---')
    found_set = {str(c).strip() for c in found_cols}
    for db_field, xlsx_header in column_map.items():
        status = '✓' if xlsx_header in found_set else '✗  NOT FOUND'
        log(f'  {status}  {xlsx_header!r:40s} → {db_field}')


# ============================================================
# Nokia PM
# ============================================================

def inspect_nokia():
    log('=' * 60)
    log('NOKIA PM SERVER')
    log(f"  Host: {NOKIA_PM_SERVER['host']}")
    log('=' * 60)

    try:
        ssh, sftp = _open_sftp(NOKIA_PM_SERVER)
    except Exception as e:
        log(f'  CONNECTION FAILED: {e}')
        return

    try:
        for tech, remote_dir in NOKIA_PM_SERVER['dirs'].items():
            log(f'\n  [Tech: {tech}]  dir: {remote_dir}')
            fname, rpath = latest_xlsx(sftp, remote_dir)
            if not rpath:
                log('  No XLSX files found.')
                continue
            log(f'  Downloading latest: {fname}')
            tmp = download_to_tmp(sftp, rpath)
            df = pd.read_excel(tmp, engine='openpyxl', nrows=0)
            cols = list(df.columns)
            log(f'  Columns ({len(cols)}):')
            for c in cols:
                log(f'    • {repr(c)}')
            print_mapping_diff(cols, NOKIA_PM_COLUMN_MAPS.get(tech, {}), f'Nokia {tech}')
            os.unlink(tmp)
    finally:
        sftp.close(); ssh.close()


# ============================================================
# Huawei PM
# ============================================================

def inspect_huawei():
    log('\n' + '=' * 60)
    log('HUAWEI PM SERVER')
    log(f"  Host: {HUAWEI_PM_SERVER['host']}")
    log('=' * 60)

    try:
        ssh, sftp = _open_sftp(HUAWEI_PM_SERVER)
    except Exception as e:
        log(f'  CONNECTION FAILED: {e}')
        return

    try:
        remote_dir = HUAWEI_PM_SERVER['remote_dir']
        log(f'  Remote dir: {remote_dir}')
        fname, rpath = latest_xlsx(sftp, remote_dir)
        if not rpath:
            log('  No XLSX files found.')
            return
        log(f'  Downloading latest: {fname}')
        tmp = download_to_tmp(sftp, rpath)
        print_excel_headers(tmp, 'Huawei PM')

        # Also check mapping for each sheet
        xl = pd.ExcelFile(tmp, engine='openpyxl')
        for tech, sheet_name in HUAWEI_SHEET_TECH_MAP.items():
            actual = next((s for s in xl.sheet_names
                           if s.lower() == sheet_name.lower()), None)
            if actual:
                df = xl.parse(actual, nrows=0)
                print_mapping_diff(df.columns, HUAWEI_PM_COLUMN_MAPS.get(tech, {}), f'Huawei {tech}')
        os.unlink(tmp)
    finally:
        sftp.close(); ssh.close()


# ============================================================
# Metadata
# ============================================================

def inspect_metadata():
    log('\n' + '=' * 60)
    log('METADATA SERVER')
    log(f"  Host: {METADATA_SERVER['host']}")
    log('=' * 60)

    try:
        ssh, sftp = _open_sftp(METADATA_SERVER)
    except Exception as e:
        log(f'  CONNECTION FAILED: {e}')
        return

    try:
        root = METADATA_SERVER['root_dir']
        log(f'  Root dir: {root}')

        # List root contents
        entries = sftp.listdir_attr(root)
        log(f'  Root contents ({len(entries)} items):')
        for e in sorted(entries, key=lambda x: x.filename):
            kind = 'DIR' if stat.S_ISDIR(e.st_mode) else 'file'
            log(f'    [{kind}] {e.filename}')

        # Find newest subdir
        subdirs = [e for e in entries if stat.S_ISDIR(e.st_mode)]
        if not subdirs:
            log('  No subdirectories — trying root directly for XLSX files.')
            target_dir = root
        else:
            subdirs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
            target_dir = f'{root.rstrip("/")}/{subdirs[0].filename}'
            log(f'\n  Newest subdir: {target_dir}')
            sub_entries = sftp.listdir_attr(target_dir)
            log(f'  Subdir contents ({len(sub_entries)} items):')
            for e in sorted(sub_entries, key=lambda x: x.filename):
                kind = 'DIR' if stat.S_ISDIR(e.st_mode) else 'file'
                log(f'    [{kind}] {e.filename}')

        # Download and inspect each xlsx found
        sub_files = sftp.listdir_attr(target_dir)
        xlsx_files = [e for e in sub_files
                      if not stat.S_ISDIR(e.st_mode)
                      and e.filename.lower().endswith(EXCEL_EXTS)]
        xlsx_files.sort(key=lambda e: e.st_mtime or 0, reverse=True)

        for xf in xlsx_files:
            rpath = f'{target_dir.rstrip("/")}/{xf.filename}'
            log(f'\n  Inspecting: {xf.filename}')
            tmp = download_to_tmp(sftp, rpath)
            df = pd.read_excel(tmp, engine='openpyxl', nrows=0)
            cols = list(df.columns)
            log(f'  Columns ({len(cols)}):')
            for c in cols:
                log(f'    • {repr(c)}')
            # Use the column map for whichever tech the filename starts with,
            # falling back to the combined map of all technologies.
            stem = os.path.splitext(xf.filename)[0].upper()
            meta_map = {}
            for t, cmap in METADATA_CSV_COLUMN_MAPS.items():
                if stem.startswith(t.upper()):
                    meta_map = cmap
                    break
            if not meta_map:
                # Flatten all maps for a broad check
                for cmap in METADATA_CSV_COLUMN_MAPS.values():
                    meta_map.update(cmap)
            print_mapping_diff(cols, meta_map, xf.filename)
            os.unlink(tmp)

    finally:
        sftp.close(); ssh.close()


# ============================================================
# Main
# ============================================================

if __name__ == '__main__':
    log(f'Header Inspection Report — {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    log('Run from a machine with network access to all three servers.')
    log('')

    inspect_nokia()
    inspect_huawei()
    inspect_metadata()

    log('\n' + '=' * 60)
    log('DONE — copy the column names above into sync_config.py')
    log('=' * 60)

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\nReport saved to: {REPORT_PATH}')
