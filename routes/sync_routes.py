"""
Sync Routes
API endpoints for sync status, history, and manual triggers.
Admin-only.
"""

from flask import Blueprint, request, jsonify, redirect, url_for
from functools import wraps
import sqlite3

from database_enhanced import get_user_by_session

sync_bp = Blueprint('sync', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        session_token = request.cookies.get('session_token')
        if not session_token:
            return jsonify({'error': 'Unauthorized'}), 401
        user = get_user_by_session(session_token)
        if not user:
            return jsonify({'error': 'Unauthorized'}), 401
        role = user.get('role') if isinstance(user, dict) else user[6]
        if role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


@sync_bp.route('/api/sync/status', methods=['GET'])
@admin_required
def sync_status():
    """Return scheduler job info and last sync times per type/technology."""
    from sync.scheduler import get_scheduler

    scheduler = get_scheduler()
    jobs = []
    if scheduler:
        for job in scheduler.get_jobs():
            next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else 'N/A'
            jobs.append({'id': job.id, 'name': job.name, 'next_run': next_run})

    # Last sync per type/technology from sync_log
    conn = sqlite3.connect('ncm_users.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT sync_type, technology, status, rows_affected, message, started_at
        FROM sync_log
        WHERE id IN (
            SELECT MAX(id) FROM sync_log GROUP BY sync_type, technology
        )
        ORDER BY sync_type, technology
    ''')
    last_syncs = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return jsonify({'success': True, 'jobs': jobs, 'last_syncs': last_syncs})


@sync_bp.route('/api/sync/history', methods=['GET'])
@admin_required
def sync_history():
    """Return recent sync log entries."""
    limit = request.args.get('limit', 50, type=int)
    conn = sqlite3.connect('ncm_users.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT sync_type, technology, status, rows_affected, message, started_at
        FROM sync_log
        ORDER BY id DESC
        LIMIT ?
    ''', (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify({'success': True, 'history': rows})


@sync_bp.route('/api/sync/trigger/pm', methods=['POST'])
@admin_required
def trigger_pm():
    """Manually trigger a PM data pull now."""
    try:
        from sync.scheduler import trigger_pm_now
        import threading
        t = threading.Thread(target=trigger_pm_now, daemon=True)
        t.start()
        return jsonify({'success': True, 'message': 'PM pull triggered in background.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/trigger/metadata', methods=['POST'])
@admin_required
def trigger_metadata():
    """Manually trigger a metadata pull now."""
    try:
        from sync.scheduler import trigger_metadata_now
        import threading
        t = threading.Thread(target=trigger_metadata_now, daemon=True)
        t.start()
        return jsonify({'success': True, 'message': 'Metadata pull triggered in background.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/test', methods=['GET'])
@admin_required
def test_connectivity():
    """
    Test SFTP connectivity to all three servers without downloading anything.
    For the metadata server, walk the full directory tree so the actual layout
    is visible — this makes it easy to diagnose wrong paths or empty folders.
    """
    import stat
    import paramiko
    from sync_config import NOKIA_PM_SERVER, HUAWEI_PM_SERVER, METADATA_SERVER

    EXCEL_EXTS = ('.xlsx', '.xls', '.csv')

    def _sftp_connect(cfg):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=cfg['host'],
            port=cfg.get('port', 22),
            username=cfg.get('username', ''),
            password=cfg.get('password', ''),
            timeout=10,
        )
        return ssh, ssh.open_sftp()

    def _list_dir(sftp, path):
        """Return (subdirs, files) entry lists for path."""
        try:
            entries = sftp.listdir_attr(path)
        except Exception as e:
            return [], [], str(e)
        subdirs = [e for e in entries if stat.S_ISDIR(e.st_mode)]
        files   = [e for e in entries if not stat.S_ISDIR(e.st_mode)]
        return subdirs, files, None

    def _excel_files(files):
        return [e.filename for e in files if e.filename.lower().endswith(EXCEL_EXTS)]

    results = {}

    # ── Nokia PM ──────────────────────────────────────────────────────────
    name = 'nokia_pm'
    cfg  = NOKIA_PM_SERVER
    host = cfg.get('host', '')
    if not host:
        results[name] = {'status': 'skipped', 'reason': 'No host configured'}
    else:
        try:
            ssh, sftp = _sftp_connect(cfg)
            dirs_result = {}
            for tech, remote_dir in cfg['dirs'].items():
                subdirs, files, err = _list_dir(sftp, remote_dir)
                if err:
                    dirs_result[tech] = {'remote_dir': remote_dir, 'error': err}
                else:
                    xlsx = _excel_files(files)
                    dirs_result[tech] = {
                        'remote_dir':   remote_dir,
                        'total_items':  len(subdirs) + len(files),
                        'excel_files':  len(xlsx),
                        'sample_excel': xlsx[:5],
                    }
            sftp.close(); ssh.close()
            results[name] = {'status': 'ok', 'host': host, 'dirs': dirs_result}
        except Exception as e:
            results[name] = {'status': 'error', 'host': host, 'error': str(e)}

    # ── Huawei PM ─────────────────────────────────────────────────────────
    name = 'huawei_pm'
    cfg  = HUAWEI_PM_SERVER
    host = cfg.get('host', '')
    if not host:
        results[name] = {'status': 'skipped', 'reason': 'No host configured'}
    else:
        try:
            ssh, sftp = _sftp_connect(cfg)
            remote_dir = cfg.get('remote_dir', '/')
            subdirs, files, err = _list_dir(sftp, remote_dir)
            if err:
                # Fall back to home dir
                remote_dir = sftp.normalize('.')
                subdirs, files, err2 = _list_dir(sftp, remote_dir)
            xlsx = _excel_files(files)
            sftp.close(); ssh.close()
            results[name] = {
                'status':       'ok' if not err else 'error',
                'host':         host,
                'remote_dir':   remote_dir,
                'total_items':  len(subdirs) + len(files),
                'excel_files':  len(xlsx),
                'sample_excel': xlsx[:5],
            }
        except Exception as e:
            results[name] = {'status': 'error', 'host': host, 'error': str(e)}

    # ── Metadata — full directory tree ────────────────────────────────────
    name = 'metadata'
    cfg  = METADATA_SERVER
    host = cfg.get('host', '')
    if not host:
        results[name] = {'status': 'skipped', 'reason': 'No host configured'}
    else:
        try:
            ssh, sftp = _sftp_connect(cfg)
            root = cfg.get('root_dir', '/')

            # Level 1: root
            subdirs_l1, files_l1, err = _list_dir(sftp, root)
            if err:
                root = sftp.normalize('.')
                subdirs_l1, files_l1, _ = _list_dir(sftp, root)

            tree = {
                'root':         root,
                'root_items':   [e.filename for e in sorted(subdirs_l1 + files_l1, key=lambda x: x.filename)],
                'latest_folder': None,
                'structure':    {},
            }

            if subdirs_l1:
                # Level 2: newest subdir (by mtime)
                subdirs_l1.sort(key=lambda e: e.st_mtime or 0, reverse=True)
                latest = subdirs_l1[0]
                latest_path = f'{root.rstrip("/")}/{latest.filename}'
                tree['latest_folder'] = latest.filename

                subdirs_l2, files_l2, _ = _list_dir(sftp, latest_path)
                direct_xlsx = _excel_files(files_l2)

                if subdirs_l2:
                    # Level 3: tech subfolders inside the latest folder
                    for sub in subdirs_l2:
                        sub_path = f'{latest_path}/{sub.filename}'
                        _, files_l3, sub_err = _list_dir(sftp, sub_path)
                        if sub_err:
                            tree['structure'][sub.filename] = {'error': sub_err}
                        else:
                            xlsx_in_sub = _excel_files(files_l3)
                            all_files = [e.filename for e in files_l3]
                            tree['structure'][sub.filename] = {
                                'path':        sub_path,
                                'total_files': len(files_l3),
                                'excel_files': xlsx_in_sub,
                                'all_files':   all_files,
                            }
                    if direct_xlsx:
                        tree['structure']['_direct_in_latest'] = {
                            'path':        latest_path,
                            'excel_files': direct_xlsx,
                        }
                else:
                    # Flat structure — files directly in the latest folder
                    all_files = [e.filename for e in files_l2]
                    tree['structure']['_flat'] = {
                        'path':        latest_path,
                        'total_files': len(files_l2),
                        'excel_files': direct_xlsx,
                        'all_files':   all_files,
                    }
            else:
                # No subfolders at root — check root directly
                direct_xlsx = _excel_files(files_l1)
                tree['structure']['_root_flat'] = {
                    'path':        root,
                    'total_files': len(files_l1),
                    'excel_files': direct_xlsx,
                }

            sftp.close(); ssh.close()
            results[name] = {'status': 'ok', 'host': host, 'tree': tree}
        except Exception as e:
            results[name] = {'status': 'error', 'host': host, 'error': str(e)}

    return jsonify({'success': True, 'results': results})


@sync_bp.route('/api/sync/inspect_local', methods=['GET'])
@admin_required
def inspect_local():
    """
    Read column headers from the most recently downloaded file in each
    sync_downloads sub-directory and compare them against the configured
    column maps.  No SFTP connection required — purely local file reads.

    Returns a report showing:
      - which files were found
      - actual column names in each file
      - which configured mappings match / are missing
    """
    import os
    import glob as _glob

    try:
        import pandas as pd
    except ImportError:
        return jsonify({'error': 'pandas not installed'}), 500

    from sync_config import (
        NOKIA_PM_COLUMN_MAPS, HUAWEI_PM_COLUMN_MAPS,
        HUAWEI_SHEET_TECH_MAP, METADATA_CSV_COLUMN_MAPS,
        LOCAL_DOWNLOAD_DIR,
    )

    DATA_EXTS = ('.xlsx', '.xls', '.csv')

    def _newest_file(directory):
        """Return the most recently modified data file in directory, or None."""
        if not os.path.isdir(directory):
            return None
        candidates = [
            f for f in (os.path.join(directory, n) for n in os.listdir(directory))
            if os.path.isfile(f) and f.lower().endswith(DATA_EXTS)
        ]
        return max(candidates, key=os.path.getmtime) if candidates else None

    def _read_headers(file_path):
        """Return (columns, sheets, error)."""
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == '.csv':
                df = pd.read_csv(file_path, nrows=0)
                return list(df.columns), None, None
            xl = pd.ExcelFile(file_path, engine='openpyxl')
            sheets = {}
            for s in xl.sheet_names:
                df = xl.parse(s, nrows=0)
                sheets[s] = list(df.columns)
            return None, sheets, None
        except Exception as e:
            return None, None, str(e)

    def _check_map(actual_cols, column_map):
        """Return {src_col: 'ok'|'MISSING'} for each value in column_map."""
        actual_set = {str(c).strip() for c in actual_cols}
        return {
            src_col: ('ok' if src_col in actual_set else 'MISSING')
            for src_col in column_map.values() if src_col
        }

    report = {}

    # ── Nokia PM ─────────────────────────────────────────────────────
    nokia_dir = os.path.join(LOCAL_DOWNLOAD_DIR, 'pm_nokia')
    nokia_file = _newest_file(nokia_dir)
    if not nokia_file:
        report['nokia_pm'] = {'status': 'no_files', 'dir': nokia_dir}
    else:
        cols, _, err = _read_headers(nokia_file)
        if err:
            report['nokia_pm'] = {'status': 'read_error', 'file': nokia_file, 'error': err}
        else:
            # Guess tech from filename prefix
            fname = os.path.basename(nokia_file).upper()
            tech  = next((t for t in NOKIA_PM_COLUMN_MAPS if fname.startswith(t)), None)
            cmap  = NOKIA_PM_COLUMN_MAPS.get(tech, {}) if tech else {}
            report['nokia_pm'] = {
                'status':        'ok',
                'file':          nokia_file,
                'detected_tech': tech,
                'columns':       cols,
                'mapping_check': _check_map(cols, cmap) if cmap else 'no map for detected tech',
            }

    # ── Huawei PM ────────────────────────────────────────────────────
    huawei_dir  = os.path.join(LOCAL_DOWNLOAD_DIR, 'pm_huawei')
    huawei_file = _newest_file(huawei_dir)
    if not huawei_file:
        report['huawei_pm'] = {'status': 'no_files', 'dir': huawei_dir}
    else:
        cols, sheets, err = _read_headers(huawei_file)
        if err:
            report['huawei_pm'] = {'status': 'read_error', 'file': huawei_file, 'error': err}
        else:
            sheet_report = {}
            for tech, sheet_name in HUAWEI_SHEET_TECH_MAP.items():
                actual_sheet = next(
                    (s for s in (sheets or {}) if s.lower() == sheet_name.lower()), None
                )
                if not actual_sheet:
                    sheet_report[tech] = {
                        'sheet': sheet_name, 'found': False,
                        'available_sheets': list(sheets.keys()) if sheets else [],
                    }
                else:
                    sheet_cols = sheets[actual_sheet]
                    cmap       = HUAWEI_PM_COLUMN_MAPS.get(tech, {})
                    sheet_report[tech] = {
                        'sheet':         actual_sheet,
                        'found':         True,
                        'columns':       sheet_cols,
                        'mapping_check': _check_map(sheet_cols, cmap),
                    }
            report['huawei_pm'] = {
                'status': 'ok',
                'file':   huawei_file,
                'sheets': sheet_report,
            }

    # ── Metadata ─────────────────────────────────────────────────────
    meta_dir = os.path.join(LOCAL_DOWNLOAD_DIR, 'metadata')
    if not os.path.isdir(meta_dir):
        report['metadata'] = {'status': 'no_files', 'dir': meta_dir}
    else:
        # Collect one newest file per detected technology key
        meta_files = [
            os.path.join(meta_dir, n) for n in os.listdir(meta_dir)
            if os.path.isfile(os.path.join(meta_dir, n))
            and os.path.join(meta_dir, n).lower().endswith(DATA_EXTS)
        ]
        meta_files.sort(key=os.path.getmtime, reverse=True)

        if not meta_files:
            report['metadata'] = {'status': 'no_files', 'dir': meta_dir}
        else:
            meta_report = {}
            seen_techs  = set()
            for fpath in meta_files:
                fname_upper = os.path.basename(fpath).upper()
                tech = next(
                    (t for t in sorted(METADATA_CSV_COLUMN_MAPS, key=len, reverse=True)
                     if fname_upper.startswith(t.upper())),
                    None,
                )
                if tech in seen_techs:
                    continue
                seen_techs.add(tech or fname_upper)
                cols, _, err = _read_headers(fpath)
                cmap = METADATA_CSV_COLUMN_MAPS.get(tech, {}) if tech else {}
                meta_report[tech or os.path.basename(fpath)] = {
                    'file':          fpath,
                    'columns':       cols if cols else '(excel — see sheets)',
                    'mapping_check': _check_map(cols or [], cmap) if cmap else 'no column map matched',
                }
                if len(seen_techs) >= len(METADATA_CSV_COLUMN_MAPS) + 3:
                    break  # enough samples

            report['metadata'] = {'status': 'ok', 'dir': meta_dir, 'files': meta_report}

    return jsonify({'success': True, 'report': report})
