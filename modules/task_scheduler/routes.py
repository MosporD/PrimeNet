"""
Configuration Management Task Scheduler routes.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from database_enhanced import get_db, get_user_by_session, log_activity
from db.runtime import adapt_placeholders
from sync_config import PROJECT_ROOT

task_scheduler_bp = Blueprint(
    'task_scheduler',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/task_scheduler/static',
)

_TASK_UPLOAD_DIR = os.path.join(PROJECT_ROOT, 'uploads', 'task_scheduler', 'inputs')
_RESULT_UPLOAD_DIR = os.path.join(PROJECT_ROOT, 'uploads', 'task_scheduler', 'results')
_ALLOWED_RESULT_EXTENSIONS = {
    '.xml', '.txt', '.csv', '.xlsx', '.xls', '.json', '.zip', '.gz', '.log'
}
_PRIVILEGED_ROLES = {'admin', 'ran_config_user'}
_DELETE_ROLES = {'admin', 'noc_sys'}
_INPUT_FILE_POLICY = {
    'huawei': {
        'extensions': {'.xml', '.zip', '.cfg', '.txt'},
        'max_size_bytes': 200 * 1024 * 1024,
    },
    'nokia': {
        'extensions': {'.xml', '.zip', '.conf', '.txt'},
        'max_size_bytes': 200 * 1024 * 1024,
    },
    'mixed': {
        'extensions': {'.xml', '.zip'},
        'max_size_bytes': 200 * 1024 * 1024,
    },
}
_RESULT_FILE_MAX_BYTES = 200 * 1024 * 1024


def _ensure_upload_dirs():
    os.makedirs(_TASK_UPLOAD_DIR, exist_ok=True)
    os.makedirs(_RESULT_UPLOAD_DIR, exist_ok=True)


def _ensure_tables():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(adapt_placeholders('''
        CREATE TABLE IF NOT EXISTS config_scheduler_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT 'mixed',
            schedule_mode TEXT NOT NULL DEFAULT 'run_now',
            scheduled_at TIMESTAMP,
            run_mode TEXT NOT NULL DEFAULT 'serial',
            execution_order TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            completion_notes TEXT,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    '''))
    cur.execute(adapt_placeholders('''
        CREATE TABLE IF NOT EXISTS config_scheduler_task_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            original_file_name TEXT NOT NULL,
            stored_file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_order INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES config_scheduler_tasks(id) ON DELETE CASCADE
        )
    '''))
    cur.execute(adapt_placeholders('''
        CREATE TABLE IF NOT EXISTS config_scheduler_result_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            original_file_name TEXT NOT NULL,
            stored_file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES config_scheduler_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (uploaded_by) REFERENCES users(id)
        )
    '''))
    conn.commit()
    conn.close()


def _current_user():
    token = request.cookies.get('session_token')
    return get_user_by_session(token) if token else None


def _format_user(user):
    if not user:
        return None
    return {
        'id': user.get('id'),
        'username': user.get('username'),
        'role': user.get('role'),
    }


def _is_privileged(user):
    return (user.get('role') or '').lower() in _PRIVILEGED_ROLES


def _can_delete_tasks(user):
    return (user.get('role') or '').lower() in _DELETE_ROLES


def _allowed_result_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename or '')
    return ext.lower() in _ALLOWED_RESULT_EXTENSIONS


def _file_size_bytes(file_storage) -> int:
    try:
        if getattr(file_storage, 'content_length', None) is not None:
            return int(file_storage.content_length)
    except Exception:
        pass
    stream = file_storage.stream
    current = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(current, os.SEEK_SET)
    return int(size)


def _validate_input_file(vendor: str, file_storage):
    policy = _INPUT_FILE_POLICY.get(vendor, _INPUT_FILE_POLICY['mixed'])
    _, ext = os.path.splitext(file_storage.filename or '')
    ext = ext.lower()
    if ext not in policy['extensions']:
        allowed = ', '.join(sorted(policy['extensions']))
        return f'Unsupported file type for {vendor}: {file_storage.filename}. Allowed: {allowed}'
    size = _file_size_bytes(file_storage)
    if size > policy['max_size_bytes']:
        max_mb = int(policy['max_size_bytes'] / (1024 * 1024))
        return f'File too large for {vendor}: {file_storage.filename}. Maximum is {max_mb}MB.'
    return None


def _validate_result_file(file_storage):
    if not _allowed_result_file(file_storage.filename):
        allowed = ', '.join(sorted(_ALLOWED_RESULT_EXTENSIONS))
        return f'Unsupported result file type: {file_storage.filename}. Allowed: {allowed}'
    size = _file_size_bytes(file_storage)
    if size > _RESULT_FILE_MAX_BYTES:
        max_mb = int(_RESULT_FILE_MAX_BYTES / (1024 * 1024))
        return f'Result file too large: {file_storage.filename}. Maximum is {max_mb}MB.'
    return None


def _extract_username(user):
    return (user.get('username') or 'user').strip() or 'user'


def _default_task_name(user):
    return f"{_extract_username(user)}.{datetime.now().strftime('%Y%m%d')}"


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _current_user()
        if not user:
            return redirect(url_for('auth.login_page'))
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


@task_scheduler_bp.route('/config-task-scheduler')
@login_required
def scheduler_page():
    _ensure_upload_dirs()
    _ensure_tables()
    user = _current_user()
    return render_template(
        'task_scheduler.html',
        user=_format_user(user),
        can_manage_tasks=_is_privileged(user),
        can_create_tasks=True,
    )


@task_scheduler_bp.route('/api/config-task-scheduler/tasks', methods=['GET'])
@login_required
def list_tasks():
    _ensure_tables()
    user = _current_user()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(adapt_placeholders('''
        SELECT t.*, u.username AS creator_username
        FROM config_scheduler_tasks t
        LEFT JOIN users u ON t.created_by = u.id
        ORDER BY t.created_at DESC
    '''))
    tasks = [dict(r) for r in cur.fetchall()]

    for task in tasks:
        cur.execute(adapt_placeholders('''
            SELECT id, original_file_name, file_order, created_at
            FROM config_scheduler_task_files
            WHERE task_id = ?
            ORDER BY file_order ASC, id ASC
        '''), (task['id'],))
        task['files'] = [dict(r) for r in cur.fetchall()]
        cur.execute(adapt_placeholders('''
            SELECT id, original_file_name, created_at
            FROM config_scheduler_result_files
            WHERE task_id = ?
            ORDER BY id ASC
        '''), (task['id'],))
        task['result_files'] = [dict(r) for r in cur.fetchall()]
    conn.close()
    policy_summary = {
        key: {
            'extensions': sorted(list(value['extensions'])),
            'max_size_bytes': value['max_size_bytes'],
        }
        for key, value in _INPUT_FILE_POLICY.items()
    }
    return jsonify({
        'success': True,
        'tasks': tasks,
        'default_task_name': _default_task_name(user),
        'can_create_tasks': True,
        'can_manage_tasks': _is_privileged(user),
        'can_delete_tasks': _can_delete_tasks(user),
        'input_file_policy': policy_summary,
        'result_max_size_bytes': _RESULT_FILE_MAX_BYTES,
        'result_allowed_extensions': sorted(list(_ALLOWED_RESULT_EXTENSIONS)),
    })


@task_scheduler_bp.route('/api/config-task-scheduler/tasks', methods=['POST'])
@login_required
def create_task():
    _ensure_upload_dirs()
    _ensure_tables()
    user = _current_user()
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'Please upload at least one file.'}), 400

    for f in files:
        if not f or not f.filename:
            return jsonify({'error': 'One of the uploaded files is invalid.'}), 400

    task_name = (request.form.get('task_name') or '').strip() or _default_task_name(user)
    vendor = (request.form.get('vendor') or 'mixed').strip().lower()
    schedule_mode = (request.form.get('schedule_mode') or 'run_now').strip().lower()
    scheduled_at = (request.form.get('scheduled_at') or '').strip()
    run_mode = (request.form.get('run_mode') or 'serial').strip().lower()
    execution_order = (request.form.get('execution_order') or '').strip()

    if vendor not in {'huawei', 'nokia', 'mixed'}:
        return jsonify({'error': 'Invalid vendor value.'}), 400
    if schedule_mode not in {'run_now', 'scheduled'}:
        return jsonify({'error': 'Invalid schedule mode.'}), 400
    if run_mode not in {'serial', 'parallel'}:
        return jsonify({'error': 'Invalid run mode.'}), 400
    if schedule_mode == 'scheduled' and not scheduled_at:
        return jsonify({'error': 'Scheduled time is required for scheduled mode.'}), 400
    for f in files:
        error = _validate_input_file(vendor, f)
        if error:
            return jsonify({'error': error}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(adapt_placeholders('''
        INSERT INTO config_scheduler_tasks (
            task_name, vendor, schedule_mode, scheduled_at, run_mode, execution_order, status, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
    '''), (
        task_name,
        vendor,
        schedule_mode,
        scheduled_at if schedule_mode == 'scheduled' else None,
        run_mode,
        execution_order,
        user['id'],
    ))
    task_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    if task_id is None:
        cur.execute(adapt_placeholders('SELECT MAX(id) AS max_id FROM config_scheduler_tasks WHERE created_by = ?'), (user['id'],))
        row = cur.fetchone()
        task_id = row['max_id'] if row else None

    orders_raw = request.form.getlist('file_order')
    parsed_orders = []
    for idx in range(len(files)):
        try:
            parsed_orders.append(max(1, int(orders_raw[idx])))
        except Exception:
            parsed_orders.append(idx + 1)

    for idx, f in enumerate(files):
        original_name = secure_filename(f.filename)
        stored_name = f"{task_id}_{idx + 1}_{uuid.uuid4().hex[:10]}_{original_name}"
        out_path = os.path.join(_TASK_UPLOAD_DIR, stored_name)
        f.save(out_path)
        cur.execute(adapt_placeholders('''
            INSERT INTO config_scheduler_task_files (
                task_id, original_file_name, stored_file_name, file_path, file_order
            ) VALUES (?, ?, ?, ?, ?)
        '''), (task_id, original_name, stored_name, out_path, parsed_orders[idx]))

    conn.commit()
    conn.close()
    log_activity(user['id'], 'config_task_create', f'Created scheduler task {task_name} (id={task_id})')
    return jsonify({'success': True, 'task_id': task_id, 'message': 'Task created successfully.'})


@task_scheduler_bp.route('/api/config-task-scheduler/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def delete_task(task_id: int):
    _ensure_tables()
    user = _current_user()
    if not _can_delete_tasks(user):
        return jsonify({'error': 'Only Owner and NOC SYS can delete tasks.'}), 403

    conn = get_db()
    cur = conn.cursor()
    cur.execute(adapt_placeholders('SELECT id, task_name FROM config_scheduler_tasks WHERE id = ?'), (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Task not found.'}), 404

    cur.execute(adapt_placeholders('DELETE FROM config_scheduler_tasks WHERE id = ?'), (task_id,))
    conn.commit()
    conn.close()
    log_activity(user['id'], 'config_task_delete', f'Deleted scheduler task {task_id}')
    return jsonify({'success': True, 'message': 'Task deleted successfully.'})


@task_scheduler_bp.route('/api/config-task-scheduler/tasks/<int:task_id>/complete', methods=['POST'])
@login_required
def complete_task(task_id: int):
    _ensure_upload_dirs()
    _ensure_tables()
    user = _current_user()
    if not _is_privileged(user):
        return jsonify({'error': 'Only Owner and RNC User can finish tasks.'}), 403

    completion_status = (request.form.get('completion_status') or '').strip().lower()
    completion_notes = (request.form.get('completion_notes') or '').strip()
    if completion_status not in {'completed', 'partial_completed', 'failed'}:
        return jsonify({'error': 'Completion status must be completed, partial_completed, or failed.'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(adapt_placeholders('SELECT * FROM config_scheduler_tasks WHERE id = ?'), (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Task not found.'}), 404
    task = dict(row)
    if task['status'] in {'completed', 'partial_completed', 'failed'}:
        conn.close()
        return jsonify({'error': 'Task is already in a final state.'}), 400

    cur.execute(adapt_placeholders('''
        UPDATE config_scheduler_tasks
        SET status = ?, completion_notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    '''), (completion_status, completion_notes, task_id))

    result_files = request.files.getlist('result_files')
    for f in result_files:
        if not f or not f.filename:
            continue
        validation_error = _validate_result_file(f)
        if validation_error:
            conn.close()
            return jsonify({'error': validation_error}), 400
        original_name = secure_filename(f.filename)
        stored_name = f"{task_id}_{uuid.uuid4().hex[:10]}_{original_name}"
        out_path = os.path.join(_RESULT_UPLOAD_DIR, stored_name)
        f.save(out_path)
        cur.execute(adapt_placeholders('''
            INSERT INTO config_scheduler_result_files (
                task_id, original_file_name, stored_file_name, file_path, uploaded_by
            ) VALUES (?, ?, ?, ?, ?)
        '''), (task_id, original_name, stored_name, out_path, user['id']))

    conn.commit()
    conn.close()
    log_activity(user['id'], 'config_task_complete', f'Finished scheduler task {task_id} as {completion_status}')
    return jsonify({'success': True, 'message': 'Task status updated.'})


@task_scheduler_bp.route('/api/config-task-scheduler/tasks/<int:task_id>/status', methods=['POST'])
@login_required
def update_task_status(task_id: int):
    _ensure_tables()
    user = _current_user()
    if not _is_privileged(user):
        return jsonify({'error': 'Only Owner and RNC User can update task status.'}), 403
    data = request.get_json(silent=True) or {}
    new_status = (data.get('status') or '').strip().lower()
    if new_status != 'in_progress':
        return jsonify({'error': 'Only in_progress transition is supported by this endpoint.'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(adapt_placeholders('SELECT * FROM config_scheduler_tasks WHERE id = ?'), (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Task not found.'}), 404
    task = dict(row)
    if task['status'] in {'completed', 'partial_completed', 'failed'}:
        conn.close()
        return jsonify({'error': 'Cannot change status of a finalized task.'}), 400
    if task['status'] == 'in_progress':
        conn.close()
        return jsonify({'success': True, 'message': 'Task already in progress.'})

    cur.execute(adapt_placeholders('''
        UPDATE config_scheduler_tasks
        SET status = 'in_progress', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    '''), (task_id,))
    conn.commit()
    conn.close()
    log_activity(user['id'], 'config_task_in_progress', f'Marked scheduler task {task_id} as in_progress')
    return jsonify({'success': True, 'message': 'Task moved to in_progress.'})


@task_scheduler_bp.route('/api/config-task-scheduler/tasks/<int:task_id>/file/<int:file_id>/download')
@login_required
def download_task_file(task_id: int, file_id: int):
    _ensure_tables()
    user = _current_user()
    if not _is_privileged(user):
        return jsonify({'error': 'Only Owner and RNC User can download task files.'}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute(adapt_placeholders('SELECT * FROM config_scheduler_tasks WHERE id = ?'), (task_id,))
    trow = cur.fetchone()
    if not trow:
        conn.close()
        return jsonify({'error': 'Task not found.'}), 404
    task = dict(trow)
    cur.execute(adapt_placeholders('''
        SELECT * FROM config_scheduler_task_files
        WHERE id = ? AND task_id = ?
    '''), (file_id, task_id))
    frow = cur.fetchone()
    conn.close()
    if not frow:
        return jsonify({'error': 'File not found.'}), 404
    item = dict(frow)
    return send_file(item['file_path'], as_attachment=True, download_name=item['original_file_name'])


@task_scheduler_bp.route('/api/config-task-scheduler/tasks/<int:task_id>/result/<int:file_id>/download')
@login_required
def download_result_file(task_id: int, file_id: int):
    _ensure_tables()
    user = _current_user()
    if not _is_privileged(user):
        return jsonify({'error': 'Only Owner and RNC User can download result files.'}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute(adapt_placeholders('SELECT * FROM config_scheduler_tasks WHERE id = ?'), (task_id,))
    trow = cur.fetchone()
    if not trow:
        conn.close()
        return jsonify({'error': 'Task not found.'}), 404
    task = dict(trow)
    cur.execute(adapt_placeholders('''
        SELECT * FROM config_scheduler_result_files
        WHERE id = ? AND task_id = ?
    '''), (file_id, task_id))
    frow = cur.fetchone()
    conn.close()
    if not frow:
        return jsonify({'error': 'Result file not found.'}), 404
    item = dict(frow)
    return send_file(item['file_path'], as_attachment=True, download_name=item['original_file_name'])
