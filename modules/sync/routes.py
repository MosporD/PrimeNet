"""
Sync Routes
API endpoints for sync status, history, and manual triggers.
Admin-only.
"""

from flask import Blueprint, request, jsonify, send_file
from functools import wraps
import csv
import io
import json
import os
import sys
from datetime import datetime
import threading
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database_enhanced import get_user_by_session
from db.runtime import connect_app, execute_query

sync_bp = Blueprint('sync', __name__)


def _log_sync(sync_type: str, technology: str, status: str, rows_affected: int = 0, message: str | None = None) -> None:
    """Write one record into sync_log; never raise to callers."""
    try:
        conn = connect_app()
        execute_query(
            conn,
            'INSERT INTO sync_log (sync_type, technology, status, rows_affected, message) VALUES (?,?,?,?,?)',
            (sync_type, technology, status, int(rows_affected or 0), message),
        )
        conn.commit()
        conn.close()
    except Exception:
        # Keep API behavior intact even if audit logging fails.
        pass


def _shorten(value, max_len: int = 1200) -> str:
    text = str(value or '').strip()
    return (text[: max_len - 3] + '...') if len(text) > max_len else text


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
    from .scheduler import get_scheduler, get_scheduler_mode_summary

    scheduler = get_scheduler()
    jobs = []
    if scheduler:
        for job in scheduler.get_jobs():
            next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else 'N/A'
            jobs.append({'id': job.id, 'name': job.name, 'next_run': next_run})

    # Last sync per type/technology from sync_log
    conn = connect_app()
    cur = execute_query(
        conn,
        '''
        SELECT sync_type, technology, status, rows_affected, message, started_at
        FROM sync_log
        WHERE id IN (
            SELECT MAX(id) FROM sync_log GROUP BY sync_type, technology
        )
        ORDER BY sync_type, technology
        ''',
    )
    last_syncs = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify(
        {
            'success': True,
            'scheduler_mode': get_scheduler_mode_summary(),
            'jobs': jobs,
            'last_syncs': last_syncs,
        }
    )


@sync_bp.route('/api/sync/progress', methods=['GET'])
@admin_required
def sync_progress():
    """Return live in-memory progress for Nokia PM, Huawei PM, and Metadata."""
    from .scheduler import get_sync_progress
    return jsonify({'success': True, 'progress': get_sync_progress()})


@sync_bp.route('/api/sync/history', methods=['GET'])
@admin_required
def sync_history():
    """Return recent sync log entries."""
    limit = request.args.get('limit', 50, type=int)
    day = (request.args.get('day') or '').strip()  # YYYY-MM-DD
    sync_type = (request.args.get('sync_type') or '').strip()
    conn = connect_app()
    where = []
    params = []
    if day:
        where.append('DATE(started_at) = ?')
        params.append(day)
    if sync_type:
        where.append('sync_type = ?')
        params.append(sync_type)
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
    params.append(limit)
    cur = execute_query(
        conn,
        f'''
        SELECT sync_type, technology, status, rows_affected, message, started_at
        FROM sync_log
        {where_sql}
        ORDER BY id DESC
        LIMIT ?
        ''',
        tuple(params),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'success': True, 'history': rows})


@sync_bp.route('/api/sync/logs/download', methods=['GET'])
@admin_required
def download_sync_logs():
    """Download latest sync_log rows as JSON and CSV in a zip archive."""
    limit = request.args.get('limit', 500, type=int) or 500
    limit = max(1, min(limit, 5000))
    conn = connect_app()
    try:
        cur = execute_query(
            conn,
            '''
            SELECT id, started_at, sync_type, technology, status, rows_affected, message
            FROM sync_log
            ORDER BY id DESC
            LIMIT ?
            ''',
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    payload = {
        'success': True,
        'generated_at': generated_at,
        'limit': limit,
        'row_count': len(rows),
        'logs': rows,
    }

    csv_buf = io.StringIO()
    fieldnames = ['id', 'started_at', 'sync_type', 'technology', 'status', 'rows_affected', 'message']
    writer = csv.DictWriter(csv_buf, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('sync_logs.json', json.dumps(payload, indent=2, ensure_ascii=False))
        zf.writestr('sync_logs.csv', csv_buf.getvalue())
    zip_buf.seek(0)

    _log_sync('admin_command', 'logs', 'ok', len(rows), f'Downloaded latest {len(rows)} sync log rows')
    return send_file(
        zip_buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'primenet_sync_logs_{stamp}.zip',
    )


@sync_bp.route('/api/sync/trigger/pm', methods=['POST'])
@admin_required
def trigger_pm():
    """Manually trigger Nokia + Huawei PM pull."""
    try:
        _log_sync('admin_command', 'pm', 'started', 0, 'Manual trigger requested: Nokia + Huawei PM pull')
        from .scheduler import trigger_pm_now
        import threading
        t = threading.Thread(target=trigger_pm_now, daemon=True)
        t.start()
        _log_sync('admin_command', 'pm', 'ok', 0, 'Manual trigger accepted: Nokia + Huawei PM pull')
        return jsonify({'success': True, 'message': 'Nokia + Huawei PM pull triggered in background.'})
    except Exception as e:
        _log_sync('admin_command', 'pm', 'error', 0, _shorten(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/trigger/nokia_pm', methods=['POST'])
@admin_required
def trigger_nokia_pm():
    """Manually trigger Nokia cells + groups pull."""
    try:
        _log_sync('admin_command', 'nokia_pm', 'started', 0, 'Manual trigger requested: Nokia cells + groups pull')
        from .scheduler import trigger_nokia_pm_now, trigger_nokia_groups_now
        import threading
        def _run():
            trigger_nokia_pm_now()
            trigger_nokia_groups_now()
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        _log_sync('admin_command', 'nokia_pm', 'ok', 0, 'Manual trigger accepted: Nokia cells + groups pull')
        return jsonify({'success': True, 'message': 'Nokia cells + groups pull triggered in background.'})
    except Exception as e:
        _log_sync('admin_command', 'nokia_pm', 'error', 0, _shorten(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/trigger/huawei_pm', methods=['POST'])
@admin_required
def trigger_huawei_pm():
    """Manually trigger Huawei cells + groups pull."""
    try:
        _log_sync('admin_command', 'huawei_pm', 'started', 0, 'Manual trigger requested: Huawei cells + groups pull')
        from .scheduler import trigger_huawei_pm_now, trigger_huawei_groups_now
        import threading
        def _run():
            trigger_huawei_pm_now()
            trigger_huawei_groups_now()
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        _log_sync('admin_command', 'huawei_pm', 'ok', 0, 'Manual trigger accepted: Huawei cells + groups pull')
        return jsonify({'success': True, 'message': 'Huawei cells + groups pull triggered in background.'})
    except Exception as e:
        _log_sync('admin_command', 'huawei_pm', 'error', 0, _shorten(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/trigger/metadata', methods=['POST'])
@admin_required
def trigger_metadata():
    """Manually trigger a metadata pull now."""
    try:
        _log_sync('admin_command', 'metadata', 'started', 0, 'Manual trigger requested: metadata pull')
        from .scheduler import trigger_metadata_now
        import threading
        t = threading.Thread(target=trigger_metadata_now, daemon=True)
        t.start()
        _log_sync('admin_command', 'metadata', 'ok', 0, 'Manual trigger accepted: metadata pull')
        return jsonify({'success': True, 'message': 'Metadata pull triggered in background.'})
    except Exception as e:
        _log_sync('admin_command', 'metadata', 'error', 0, _shorten(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/trigger/cells_hourly', methods=['POST'])
@admin_required
def trigger_cells_hourly():
    """Manually trigger hourly cells refresh (all vendors)."""
    try:
        _log_sync('admin_command', 'cells_hourly', 'started', 0, 'Manual trigger requested: hourly cells refresh')
        from .scheduler import trigger_cells_hourly_now
        t = threading.Thread(target=trigger_cells_hourly_now, daemon=True)
        t.start()
        _log_sync('admin_command', 'cells_hourly', 'ok', 0, 'Manual trigger accepted: hourly cells refresh')
        return jsonify({'success': True, 'message': 'Hourly cells refresh triggered in background.'})
    except Exception as e:
        _log_sync('admin_command', 'cells_hourly', 'error', 0, _shorten(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/trigger/groups_hourly', methods=['POST'])
@admin_required
def trigger_groups_hourly():
    """Manually trigger hourly groups refresh (all vendors)."""
    try:
        _log_sync('admin_command', 'groups_hourly', 'started', 0, 'Manual trigger requested: hourly groups refresh')
        from .scheduler import trigger_groups_hourly_now
        t = threading.Thread(target=trigger_groups_hourly_now, daemon=True)
        t.start()
        _log_sync('admin_command', 'groups_hourly', 'ok', 0, 'Manual trigger accepted: hourly groups refresh')
        return jsonify({'success': True, 'message': 'Hourly groups refresh triggered in background.'})
    except Exception as e:
        _log_sync('admin_command', 'groups_hourly', 'error', 0, _shorten(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/trigger/cells_daily', methods=['POST'])
@admin_required
def trigger_cells_daily():
    """Manually trigger daily cells refresh (all vendors)."""
    try:
        _log_sync('admin_command', 'cells_daily', 'started', 0, 'Manual trigger requested: daily cells refresh')
        from .scheduler import trigger_cells_daily_now
        t = threading.Thread(target=trigger_cells_daily_now, daemon=True)
        t.start()
        _log_sync('admin_command', 'cells_daily', 'ok', 0, 'Manual trigger accepted: daily cells refresh')
        return jsonify({'success': True, 'message': 'Daily cells refresh triggered in background.'})
    except Exception as e:
        _log_sync('admin_command', 'cells_daily', 'error', 0, _shorten(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/trigger/groups_daily', methods=['POST'])
@admin_required
def trigger_groups_daily():
    """Manually trigger daily groups refresh (all vendors)."""
    try:
        _log_sync('admin_command', 'groups_daily', 'started', 0, 'Manual trigger requested: daily groups refresh')
        from .scheduler import trigger_groups_daily_now
        t = threading.Thread(target=trigger_groups_daily_now, daemon=True)
        t.start()
        _log_sync('admin_command', 'groups_daily', 'ok', 0, 'Manual trigger accepted: daily groups refresh')
        return jsonify({'success': True, 'message': 'Daily groups refresh triggered in background.'})
    except Exception as e:
        _log_sync('admin_command', 'groups_daily', 'error', 0, _shorten(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/trigger/nokia_groups', methods=['POST'])
@admin_required
def trigger_nokia_groups():
    """Manually trigger Nokia groups pull."""
    try:
        _log_sync('admin_command', 'nokia_groups', 'started', 0, 'Manual trigger requested: Nokia groups pull')
        from .scheduler import trigger_nokia_groups_now
        import threading
        t = threading.Thread(target=trigger_nokia_groups_now, daemon=True)
        t.start()
        _log_sync('admin_command', 'nokia_groups', 'ok', 0, 'Manual trigger accepted: Nokia groups pull')
        return jsonify({'success': True, 'message': 'Nokia groups pull triggered in background.'})
    except Exception as e:
        _log_sync('admin_command', 'nokia_groups', 'error', 0, _shorten(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/trigger/huawei_groups', methods=['POST'])
@admin_required
def trigger_huawei_groups():
    """Manually trigger Huawei groups pull."""
    try:
        _log_sync('admin_command', 'huawei_groups', 'started', 0, 'Manual trigger requested: Huawei groups pull')
        from .scheduler import trigger_huawei_groups_now
        import threading
        t = threading.Thread(target=trigger_huawei_groups_now, daemon=True)
        t.start()
        _log_sync('admin_command', 'huawei_groups', 'ok', 0, 'Manual trigger accepted: Huawei groups pull')
        return jsonify({'success': True, 'message': 'Huawei groups pull triggered in background.'})
    except Exception as e:
        _log_sync('admin_command', 'huawei_groups', 'error', 0, _shorten(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync/import_pm_path', methods=['POST'])
@admin_required
def import_pm_path():
    """
    Import PM files from a local directory path.
    Body JSON:
      {
        "path": "C:/.../folder",
        "vendor": "all|nokia|huawei",
        "recursive": true
      }
    """
    try:
        payload = request.get_json(silent=True) or {}
        root_path = (payload.get('path') or '').strip()
        vendor = (payload.get('vendor') or 'all').strip().lower()
        recursive = bool(payload.get('recursive', True))

        if not root_path:
            _log_sync('admin_command', 'pm_local_import', 'error', 0, 'Rejected: path is required')
            return jsonify({'success': False, 'error': 'path is required'}), 400
        if vendor not in ('all', 'nokia', 'huawei'):
            _log_sync('admin_command', 'pm_local_import', 'error', 0, f'Rejected: invalid vendor "{vendor}"')
            return jsonify({'success': False, 'error': 'vendor must be all, nokia, or huawei'}), 400

        def _run():
            from .pm_processor import import_pm_from_directory
            result = import_pm_from_directory(root_path, vendor=vendor, recursive=recursive)
            if result.get('status') != 'ok':
                _log_sync('pm_local_import', vendor, 'error', 0, result.get('error'))
                return
            _log_sync(
                'pm_local_import',
                vendor,
                'ok',
                int(result.get('inserted', 0) or 0),
                f'path={root_path}; files={result.get("files", 0)}; skipped={result.get("skipped", 0)}',
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        _log_sync(
            'admin_command',
            'pm_local_import',
            'started',
            0,
            _shorten(f'Manual local import requested: path={root_path}; vendor={vendor}; recursive={recursive}'),
        )
        return jsonify({
            'success': True,
            'message': 'PM local import started in background.',
            'path': root_path,
            'vendor': vendor,
            'recursive': recursive,
        })
    except Exception as e:
        _log_sync('admin_command', 'pm_local_import', 'error', 0, _shorten(e))
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

    try:
        summary = ', '.join(
            f'{name}:{info.get("status", "unknown")}'
            for name, info in sorted(results.items())
        )
        _log_sync('admin_command', 'test_connectivity', 'ok', 0, _shorten(summary))
    except Exception:
        pass
    return jsonify({'success': True, 'results': results})


@sync_bp.route('/api/sync/inspect_local', methods=['GET'])
@admin_required
def inspect_local():
    """
    Read column headers from downloaded files in each sync_downloads
    sub-directory.  No SFTP connection required — purely local file reads.

    Returns a report showing which files were found and their actual column names.
    """
    import os

    try:
        import pandas as pd
    except ImportError:
        return jsonify({'error': 'pandas not installed'}), 500

    from sync_config import LOCAL_DOWNLOAD_DIR

    PM_FILE_EXTS = ('.xlsx', '.xls', '.xlsm', '.csv')

    def _newest_file(directory, exts=PM_FILE_EXTS):
        if not os.path.isdir(directory):
            return None
        candidates = [
            f for f in (os.path.join(directory, n) for n in os.listdir(directory))
            if os.path.isfile(f) and f.lower().endswith(exts)
        ]
        return max(candidates, key=os.path.getmtime) if candidates else None

    def _resolve_pm_zip_for_inspect(zip_path):
        """
        Pick an inner file from a PM .zip for header inspection.

        Prefer the inner ``.csv`` that parses with the **most meaningful columns**
        (same heuristic as PM ingest), not merely the largest file — Huawei zips
        often include a large one-column sidecar that would otherwise show as
        ``Unnamed: 0``.
        """
        import shutil
        import tempfile
        import zipfile

        if not str(zip_path).lower().endswith('.zip'):
            return zip_path, None, None
        tmp = tempfile.mkdtemp(prefix='inspect_pm_zip_')
        meta = {'inner_member': None, 'csv_members': 0, 'picked_by': None}

        def _cand_path(member_name: str) -> str:
            p = os.path.join(tmp, member_name.replace('/', os.sep))
            if os.path.isfile(p):
                return p
            p2 = os.path.join(tmp, os.path.basename(member_name))
            return p2 if os.path.isfile(p2) else ''

        try:
            from .pm_processor import _read_nokia_csv_best, _nokia_csv_parse_score

            with zipfile.ZipFile(zip_path, 'r') as zf:
                names = [
                    n
                    for n in zf.namelist()
                    if not n.endswith('/') and n.lower().endswith(PM_FILE_EXTS)
                ]
                if not names:
                    shutil.rmtree(tmp, ignore_errors=True)
                    return None, None, None

                csv_names = [n for n in names if n.lower().endswith('.csv')]
                book_names = [n for n in names if n.lower().endswith(('.xlsx', '.xls', '.xlsm'))]
                meta['csv_members'] = len(csv_names)

                best_csv = None  # (score, ncol, size, member, path)
                for n in csv_names:
                    zf.extract(n, tmp)
                    cand = _cand_path(n)
                    if not cand:
                        continue
                    df = _read_nokia_csv_best(cand, nrows=12000)
                    ncol = len(df.columns) if df is not None and not df.empty else 0
                    if ncol < 2:
                        continue
                    sc = _nokia_csv_parse_score(df)
                    sz = zf.getinfo(n).file_size
                    key = (sc, ncol, sz)
                    if best_csv is None or key > (best_csv[0], best_csv[1], best_csv[2]):
                        best_csv = (sc, ncol, sz, n, cand)

                if best_csv:
                    meta['inner_member'] = best_csv[3]
                    meta['picked_by'] = 'best multi-column .csv parse (ingest-style heuristic)'
                    return best_csv[4], tmp, meta

                if book_names:
                    bn = max(book_names, key=lambda n: zf.getinfo(n).file_size)
                    zf.extract(bn, tmp)
                    cand = _cand_path(bn)
                    if cand:
                        meta['inner_member'] = bn
                        meta['picked_by'] = 'largest workbook (no .csv parsed with 2+ columns)'
                        return cand, tmp, meta

                if csv_names:
                    bn = max(csv_names, key=lambda n: zf.getinfo(n).file_size)
                    zf.extract(bn, tmp)
                    cand = _cand_path(bn)
                    if cand:
                        meta['inner_member'] = bn
                        meta['picked_by'] = 'largest .csv fallback (may be one-column / non-PM)'
                        return cand, tmp, meta

            shutil.rmtree(tmp, ignore_errors=True)
            return None, None, None
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            return None, None, None

    def _read_headers(file_path):
        """Return (columns, sheets, error).  Tries openpyxl → xlrd → HTML → CSV (safe encodings)."""
        encodings = ('utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1')
        last_err = None

        def _csv_probe(sep, min_cols=1):
            kw = {'nrows': 0, 'sep': sep, 'engine': 'python', 'on_bad_lines': 'skip'}
            for enc in encodings:
                try:
                    df = pd.read_csv(file_path, encoding=enc, **kw)
                    if len(df.columns) >= min_cols:
                        return list(df.columns)
                except Exception:
                    continue
            return None

        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.csv':
            from .pm_processor import _load_pm_file, _read_nokia_csv_best

            df = _read_nokia_csv_best(file_path, nrows=8192)
            if df is not None and len(df.columns) >= 2:
                return list(df.columns), None, None
            try:
                df2 = _load_pm_file(file_path)
                if df2 is not None and len(df2.columns) >= 2:
                    return list(df2.columns), None, None
            except Exception as e:
                last_err = e
            for sep in (';', '\t', ',', '|'):
                cols = _csv_probe(sep=sep, min_cols=2)
                if cols:
                    return cols, None, None
            for enc in ('utf-16', 'utf-16-le', 'utf-16-be'):
                try:
                    for sep in ('\t', ';', ',', '|'):
                        df3 = pd.read_csv(
                            file_path,
                            encoding=enc,
                            sep=sep,
                            nrows=0,
                            engine='python',
                            on_bad_lines='skip',
                        )
                        if len(df3.columns) >= 2:
                            return list(df3.columns), None, None
                except Exception:
                    continue
            hint = str(last_err) if last_err else 'no 2+ column parse'
            return None, None, (
                'Could not read CSV with 2+ columns (refused single-column / Unnamed: 0 misread). '
                f'{hint}'
            )

        # Try Excel engines first (openpyxl handles .xlsx / .xlsm)
        xl = None
        for engine in ('openpyxl', 'xlrd'):
            try:
                xl = pd.ExcelFile(file_path, engine=engine)
                break
            except Exception as e:
                last_err = e
        if xl is not None:
            try:
                sheets = {s: list(xl.parse(s, nrows=0).columns) for s in xl.sheet_names}
                return None, sheets, None
            except Exception as e:
                last_err = e

        # Real .xlsx is a ZIP (PK\x03\x04…). If Excel engines failed, latin-1 CSV would
        # still "parse" it and show nonsense columns like "PK…" — report the real error instead.
        try:
            with open(file_path, 'rb') as f:
                sig = f.read(8)
        except OSError:
            sig = b''

        def _is_ooxml_zip(s):
            return len(s) >= 4 and s[:2] == b'PK' and s[2:4] in (b'\x03\x04', b'\x05\x06', b'\x07\x08')

        def _is_ole_xls(s):
            return len(s) >= 8 and s[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'

        if ext == '.xlsx' and _is_ooxml_zip(sig):
            msg = str(last_err) if last_err else 'unknown error'
            return None, None, (
                'This is a standard .xlsx (ZIP) file but it could not be opened as a workbook. '
                f'openpyxl/xlrd error: {msg}. '
                'If it opens in Excel, try Save As a new .xlsx; otherwise check the download is complete.'
            )
        if ext == '.xls' and _is_ole_xls(sig):
            msg = str(last_err) if last_err else 'unknown error'
            return None, None, (
                f'Legacy .xls could not be read: {msg}. '
                'You may need xlrd 1.x for .xls, or convert the file to .xlsx.'
            )

        # HTML table saved as .xlsx (common NetAct / vendor export)
        for enc in encodings:
            try:
                dfs = pd.read_html(file_path, encoding=enc)
                if not dfs:
                    continue
                wide = [d for d in dfs if len(d.columns) > 1]
                if not wide:
                    continue
                if len(wide) == 1:
                    return list(wide[0].columns), None, None
                return None, {f'table{i}': list(d.columns) for i, d in enumerate(wide)}, None
            except Exception:
                continue

        # Delimited text with wrong extension — never assume UTF-8-only (binary .xlsx hits utf-8 decode error)
        for sep in ('\t', ',', ';', '|'):
            cols = _csv_probe(sep=sep, min_cols=2)
            if cols:
                return cols, None, None

        hint = str(last_err) if last_err else 'not recognized as Excel, HTML table, or delimited text'
        return None, None, hint

    report = {}

    # ── Nokia PM ─────────────────────────────────────────────────────
    nokia_dir  = os.path.join(LOCAL_DOWNLOAD_DIR, 'pm_nokia')
    nokia_file = _newest_file(nokia_dir)
    if not nokia_file:
        report['nokia_pm'] = {'status': 'no_files', 'dir': nokia_dir}
    else:
        cols, sheets, err = _read_headers(nokia_file)
        if err:
            report['nokia_pm'] = {'status': 'read_error', 'file': nokia_file, 'error': err}
        else:
            report['nokia_pm'] = {
                'status':  'ok',
                'file':    nokia_file,
                'columns': cols if cols is not None else sheets,
            }

    # ── Huawei PM ────────────────────────────────────────────────────
    huawei_dir = os.path.join(LOCAL_DOWNLOAD_DIR, 'pm_huawei')
    huawei_file = _newest_file(huawei_dir, PM_FILE_EXTS + ('.zip',))
    if not huawei_file:
        report['huawei_pm'] = {'status': 'no_files', 'dir': huawei_dir}
    else:
        ztmp = None
        try:
            read_path, ztmp, zip_meta = _resolve_pm_zip_for_inspect(huawei_file)
            if read_path is None:
                report['huawei_pm'] = {
                    'status': 'read_error',
                    'file': huawei_file,
                    'error': 'ZIP has no .xlsx/.xls/.xlsm/.csv inside (or extract failed).',
                }
            else:
                cols, sheets, err = _read_headers(read_path)
                if err:
                    report['huawei_pm'] = {'status': 'read_error', 'file': huawei_file, 'error': err}
                else:
                    entry = {
                        'status': 'ok',
                        'file': huawei_file,
                        'columns': cols if cols is not None else sheets,
                    }
                    if zip_meta:
                        entry['inner_zip_member'] = zip_meta.get('inner_member')
                        entry['inner_pick_reason'] = zip_meta.get('picked_by')
                        entry['inner_csv_count'] = zip_meta.get('csv_members')
                    report['huawei_pm'] = entry
        finally:
            if ztmp:
                import shutil
                shutil.rmtree(ztmp, ignore_errors=True)

    # ── Metadata ─────────────────────────────────────────────────────
    meta_dir = os.path.join(LOCAL_DOWNLOAD_DIR, 'metadata')
    if not os.path.isdir(meta_dir):
        report['metadata'] = {'status': 'no_files', 'dir': meta_dir}
    else:
        meta_files = sorted(
            [
                os.path.join(meta_dir, n) for n in os.listdir(meta_dir)
                if os.path.isfile(os.path.join(meta_dir, n))
                and n.lower().endswith(PM_FILE_EXTS)
            ],
            key=os.path.getmtime,
            reverse=True,
        )
        if not meta_files:
            report['metadata'] = {'status': 'no_files', 'dir': meta_dir}
        else:
            meta_report = {}
            for fpath in meta_files[:10]:   # inspect up to 10 most recent files
                stem = os.path.splitext(os.path.basename(fpath))[0]
                cols, sheets, err = _read_headers(fpath)
                if err:
                    meta_report[stem] = {'file': fpath, 'error': err}
                else:
                    meta_report[stem] = {
                        'file':    fpath,
                        'columns': cols if cols is not None else sheets,
                    }
            report['metadata'] = {'status': 'ok', 'dir': meta_dir, 'files': meta_report}

    try:
        summary_parts = []
        for name, info in sorted(report.items()):
            status = info.get('status', 'unknown')
            if status == 'ok' and isinstance(info.get('files'), dict):
                summary_parts.append(f'{name}:ok files={len(info.get("files") or {})}')
            elif status == 'ok':
                summary_parts.append(f'{name}:ok')
            else:
                summary_parts.append(f'{name}:{status}')
        _log_sync('admin_command', 'inspect_local', 'ok', 0, _shorten('; '.join(summary_parts)))
    except Exception:
        pass
    return jsonify({'success': True, 'report': report})


@sync_bp.route('/api/sync/latest_downloads', methods=['GET'])
@admin_required
def latest_downloads():
    """
    Return recently downloaded local files per sync type.
    Query param:
      type = nokia_pm | huawei_pm | metadata | all
    """
    from sync_config import LOCAL_DOWNLOAD_DIR

    requested = (request.args.get('type') or 'all').strip().lower()
    allowed = {'nokia_pm', 'huawei_pm', 'metadata', 'all'}
    if requested not in allowed:
        requested = 'all'

    source_dirs = {
        'nokia_pm': os.path.join(LOCAL_DOWNLOAD_DIR, 'pm_nokia'),
        'huawei_pm': os.path.join(LOCAL_DOWNLOAD_DIR, 'pm_huawei'),
        'metadata': os.path.join(LOCAL_DOWNLOAD_DIR, 'metadata'),
    }
    selected = source_dirs if requested == 'all' else {requested: source_dirs[requested]}

    exts = ('.xlsx', '.xls', '.xlsm', '.csv', '.zip')
    out = {}
    for source, directory in selected.items():
        files = []
        if os.path.isdir(directory):
            for name in os.listdir(directory):
                full = os.path.join(directory, name)
                if not os.path.isfile(full):
                    continue
                if not name.lower().endswith(exts):
                    continue
                mtime = os.path.getmtime(full)
                files.append({
                    'name': name,
                    'modified_at': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'mtime': mtime,
                })
            files.sort(key=lambda x: x['mtime'], reverse=True)
            for f in files:
                f.pop('mtime', None)
        out[source] = {
            'dir': directory,
            'files': files[:12],
        }

    try:
        totals = []
        for source, payload in sorted(out.items()):
            totals.append(f'{source}:{len(payload.get("files") or [])}')
        _log_sync('admin_command', 'latest_downloads', 'ok', 0, _shorten(f'type={requested}; counts={" ,".join(totals)}'))
    except Exception:
        pass
    return jsonify({'success': True, 'downloads': out})
