"""
Group Data Processor
====================
Imports vendor group files and stores group memberships in vendor-specific DBs.
"""

import os
import re
import sqlite3
import zipfile
import tempfile
import shutil
import logging
from datetime import datetime

import pandas as pd

from sync_config import (
    METADATA_DB,
    NOKIA_GROUPS_DB,
    HUAWEI_GROUPS_DB,
)

logger = logging.getLogger(__name__)

_GROUP_KW = ('group', 'grp', 'cluster group', 'object group', 'performance group')
_CELL_KW = ('cell name', 'cell_name', 'cellname', 'cell', 'wcel', 'lncel', 'nrcel', 'bts')
_TECH_KW = ('technology', 'tech', 'rat')
_SITE_KW = ('site_id', 'site id', 'site')


def _groups_db(vendor: str) -> str:
    return NOKIA_GROUPS_DB if vendor == 'Nokia' else HUAWEI_GROUPS_DB


def _load_file(file_path: str) -> pd.DataFrame:
    try:
        return pd.read_excel(file_path, engine='openpyxl')
    except Exception:
        pass
    try:
        return pd.read_excel(file_path, engine='xlrd')
    except Exception:
        pass
    for enc in ('utf-8', 'latin-1', 'cp1252', 'iso-8859-1'):
        for sep in ('\t', ',', ';'):
            try:
                df = pd.read_csv(file_path, sep=sep, dtype=str, encoding=enc)
                if len(df.columns) > 1:
                    return df
            except Exception:
                pass
    return pd.read_csv(file_path, dtype=str, encoding='latin-1')


def _detect_col(columns, keywords):
    low_map = {c: str(c).strip().lower() for c in columns}
    for kw in keywords:
        for c, low in low_map.items():
            if kw in low:
                return c
    return None


def _norm(v):
    if v is None:
        return ''
    s = str(v).strip()
    if not s or s.lower() in ('nan', 'none', 'null'):
        return ''
    return s


def _build_metadata_index(vendor: str):
    conn = sqlite3.connect(METADATA_DB, timeout=30)
    rows = conn.execute(
        '''
        SELECT cell_name, site_id, technology
        FROM cells
        WHERE vendor = ?
        ''',
        (vendor,),
    ).fetchall()
    conn.close()
    idx = {}
    for cell_name, site_id, technology in rows:
        k = _norm(cell_name)
        if not k:
            continue
        idx[k] = (_norm(site_id), _norm(technology))
    return idx


def clear_groups_db(vendor: str):
    db = _groups_db(vendor)
    conn = sqlite3.connect(db, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('DELETE FROM group_cells')
    conn.execute('DELETE FROM groups')
    conn.commit()
    conn.close()


def _upsert_group(conn, user_id: int, name: str, description: str = '', is_shared: int = 1) -> int:
    row = conn.execute(
        'SELECT id FROM groups WHERE user_id = ? AND name = ?',
        (user_id, name),
    ).fetchone()
    if row:
        gid = int(row[0])
        conn.execute(
            'UPDATE groups SET description = ?, is_shared = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (description, is_shared, gid),
        )
        return gid
    cur = conn.execute(
        'INSERT INTO groups (user_id, name, description, is_shared) VALUES (?,?,?,?)',
        (user_id, name, description, is_shared),
    )
    return int(cur.lastrowid)


def process_group_file(file_path: str, vendor: str, default_technology: str = '') -> dict:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.zip':
        tmp_dir = tempfile.mkdtemp(prefix='group_zip_')
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                zf.extractall(tmp_dir)
            best = None
            best_key = None
            for root, _, files in os.walk(tmp_dir):
                for fn in files:
                    low = fn.lower()
                    if not low.endswith(('.xlsx', '.xls', '.xlsm', '.csv')):
                        continue
                    fp = os.path.join(root, fn)
                    prio = 0 if low.endswith(('.xlsx', '.xls', '.xlsm')) else 1
                    key = (prio, -os.path.getmtime(fp))
                    if best is None or key < best_key:
                        best = fp
                        best_key = key
            if not best:
                return {'status': 'error', 'error': f'No supported files inside ZIP: {file_path}'}
            return process_group_file(best, vendor, default_technology)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        df = _load_file(file_path)
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

    if df is None or df.empty or len(df.columns) == 0:
        return {'status': 'skipped', 'reason': 'empty_file'}

    cols = list(df.columns)
    group_col = _detect_col(cols, _GROUP_KW)
    cell_col = _detect_col(cols, _CELL_KW)
    tech_col = _detect_col(cols, _TECH_KW)
    site_col = _detect_col(cols, _SITE_KW)

    if not cell_col:
        return {'status': 'error', 'error': 'Could not detect cell column in group file'}

    if not group_col:
        stem = os.path.splitext(os.path.basename(file_path))[0]
        safe = re.sub(r'\s+', ' ', stem).strip()
        df['__group_name__'] = safe or f'{vendor} Group'
        group_col = '__group_name__'

    meta_idx = _build_metadata_index(vendor)
    db = _groups_db(vendor)
    conn = sqlite3.connect(db, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')

    imported_rows = 0
    imported_groups = set()
    # system-owned shared groups
    system_user_id = 0

    for _, r in df.iterrows():
        group_name = _norm(r.get(group_col))
        cell_name = _norm(r.get(cell_col))
        if not group_name or not cell_name:
            continue
        site_id = _norm(r.get(site_col)) if site_col else ''
        tech = _norm(r.get(tech_col)) if tech_col else ''
        if not tech:
            tech = _norm(default_technology)
        if cell_name in meta_idx:
            m_site, m_tech = meta_idx[cell_name]
            if not site_id:
                site_id = m_site
            if not tech:
                tech = m_tech
        gid = _upsert_group(conn, system_user_id, group_name, description=f'Imported from {vendor} group file', is_shared=1)
        cell_key = '||'.join([vendor, tech, site_id, cell_name])
        conn.execute(
            '''
            INSERT OR REPLACE INTO group_cells
            (group_id, cell_key, cell_name, vendor, technology, site_id, created_at)
            VALUES (?,?,?,?,?,?,?)
            ''',
            (gid, cell_key, cell_name, vendor, tech, site_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        )
        imported_rows += 1
        imported_groups.add(gid)

    conn.commit()
    conn.close()
    return {
        'status': 'ok',
        'inserted': imported_rows,
        'groups': len(imported_groups),
    }

