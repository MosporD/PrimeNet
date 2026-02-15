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
