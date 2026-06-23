"""
Drive Test Viewer routes.
Upload GPX + NMFS files and visualize drive route on map.
"""

from __future__ import annotations

import os
import re
import uuid
import math
import struct
from html import unescape
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from database_enhanced import get_user_by_session
from sync_config import PROJECT_ROOT
from utils.xml_safety import parse_xml_file

drive_test_viewer_bp = Blueprint(
    'drive_test_viewer',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/drive_test_viewer/static',
)

_UPLOAD_DIR = os.path.join(PROJECT_ROOT, 'uploads', 'drive_test_viewer')
_MAX_POINTS = 8000
_ALLOWED_GPX = {'.gpx'}
_ALLOWED_NMFS = {'.nmfs'}
_NEMO_BASE_DIR = r'C:\Program Files\Anite\Nemo Analyze'
_NEMO_FF2_PATH = os.path.join(_NEMO_BASE_DIR, 'Documentation', 'FF2.html')
_NEMO_OBJECT_MAPPER_PATH = os.path.join(_NEMO_BASE_DIR, 'object_mapper.xml')
_NEMO_REF_CACHE = {'ff2': None, 'object_mapper': None}


def _ensure_upload_dir():
    os.makedirs(_UPLOAD_DIR, exist_ok=True)


def _current_user():
    token = request.cookies.get('session_token')
    return get_user_by_session(token) if token else None


def _format_user(user):
    return {
        'id': user.get('id'),
        'username': user.get('username'),
        'role': user.get('role'),
    } if user else None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _current_user()
        if not user:
            return redirect(url_for('auth.login_page'))
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def _save_upload(file_storage, prefix: str):
    filename = secure_filename(file_storage.filename or '')
    out_name = f'{prefix}_{uuid.uuid4().hex[:10]}_{filename}'
    out_path = os.path.join(_UPLOAD_DIR, out_name)
    file_storage.save(out_path)
    return out_path, filename


def _parse_gpx(path: str):
    ns = {'g': 'http://www.topografix.com/GPX/1/1'}
    root = parse_xml_file(path)
    points = []
    times = []
    lats = []
    lngs = []

    for trkpt in root.findall('.//g:trkpt', ns):
        lat_s = trkpt.get('lat')
        lon_s = trkpt.get('lon')
        if lat_s is None or lon_s is None:
            continue
        try:
            lat = float(lat_s)
            lng = float(lon_s)
        except ValueError:
            continue
        ele_node = trkpt.find('g:ele', ns)
        time_node = trkpt.find('g:time', ns)
        ele = None
        if ele_node is not None and (ele_node.text or '').strip():
            try:
                ele = float((ele_node.text or '').strip())
            except ValueError:
                ele = None
        time_val = (time_node.text or '').strip() if time_node is not None else None

        points.append({'lat': lat, 'lng': lng, 'ele': ele, 'time': time_val})
        if time_val:
            times.append(time_val)
        lats.append(lat)
        lngs.append(lng)

    if len(points) > _MAX_POINTS:
        step = max(1, len(points) // _MAX_POINTS)
        points = points[::step]

    bounds = None
    if lats and lngs:
        bounds = {
            'min_lat': min(lats),
            'max_lat': max(lats),
            'min_lng': min(lngs),
            'max_lng': max(lngs),
        }

    return {
        'point_count': len(points),
        'start_time': times[0] if times else None,
        'end_time': times[-1] if times else None,
        'bounds': bounds,
        'points': points,
    }


def _parse_nmfs(path: str):
    with open(path, 'rb') as f:
        data = f.read()

    header_match = re.search(rb'#[A-Z]{2},,,[^\r\n\x00]{0,300}', data)
    metadata_records = []
    if header_match:
        start = max(0, header_match.start() - 8)
        scan_window = data[start : min(len(data), start + 12000)]
        for m in re.finditer(rb'#[A-Z]{2},,,[^\r\n\x00]{0,400}', scan_window):
            raw_line = m.group(0).decode('ascii', errors='ignore').strip()
            if not raw_line:
                continue
            tag = raw_line[1:3]
            metadata_records.append({
                'offset': int(start + m.start()),
                'tag': tag,
                'raw': raw_line,
            })

    tag_counts = {}
    for rec in metadata_records:
        tag = rec['tag']
        tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Measure entropy in windows to identify likely compressed/encrypted payload zones.
    window_size = 2048
    entropy_windows = []
    for i in range(0, len(data), window_size):
        chunk = data[i : i + window_size]
        if not chunk:
            continue
        freqs = {}
        for b in chunk:
            freqs[b] = freqs.get(b, 0) + 1
        n = float(len(chunk))
        entropy = 0.0
        for count in freqs.values():
            p = count / n
            entropy -= p * math.log2(p)
        entropy_windows.append({
            'offset_start': i,
            'offset_end': min(len(data), i + window_size),
            'entropy': round(entropy, 3),
        })

    high_entropy = [w for w in entropy_windows if w['entropy'] >= 7.75]

    # Scan for plausible little-endian UNIX timestamps (seconds).
    timestamp_hits = []
    for i in range(0, max(0, len(data) - 4), 4):
        v = struct.unpack_from('<I', data, i)[0]
        if 946684800 <= v <= 2208988800:  # 2000-01-01 .. 2040-01-01
            timestamp_hits.append({'offset': i, 'epoch_sec': int(v)})
            if len(timestamp_hits) >= 120:
                break

    # Try to classify payload after metadata area.
    guessed_payload_offset = metadata_records[-1]['offset'] if metadata_records else 0
    payload_slice = data[guessed_payload_offset:]
    ascii_ratio = 0.0
    if payload_slice:
        printable = sum(1 for b in payload_slice if 32 <= b <= 126)
        ascii_ratio = printable / len(payload_slice)

    text_chunks = re.findall(rb'[ -~]{8,}', data)
    all_ascii_lines = [x.decode('ascii', errors='ignore') for x in text_chunks]

    # Heuristic KPI hunting:
    # Nemo payload is often binary records without plain KPI labels.
    # We scan int16 streams and flag smooth runs that match radio-level ranges.
    def _scan_kpi_candidates(raw: bytes):
        ranges = {
            'rsrp_dbm': (-160, -40),   # LTE
            'rsrq_db': (-35, -1),      # LTE
            'rscp_dbm': (-140, -30),   # WCDMA
            'ecno_db': (-30, 5),       # WCDMA
        }
        out = {k: [] for k in ranges}
        best_series = {}
        max_bytes = min(len(raw), 180000)
        buf = raw[:max_bytes]

        # Build int16 stream once
        vals = []
        for i in range(0, len(buf) - 1, 2):
            vals.append(struct.unpack_from('<h', buf, i)[0])

        for metric, (lo, hi) in ranges.items():
            # Find contiguous runs in valid range and keep the strongest/smoothest ones.
            runs = []
            start = None
            for idx, v in enumerate(vals):
                in_range = lo <= v <= hi
                if in_range and start is None:
                    start = idx
                elif not in_range and start is not None:
                    runs.append((start, idx))
                    start = None
            if start is not None:
                runs.append((start, len(vals)))

            scored = []
            for s, e in runs:
                length = e - s
                if length < 24:
                    continue
                series = vals[s:e]
                smooth_ratio = sum(
                    1 for a, b in zip(series, series[1:]) if abs(b - a) <= 6
                ) / max(1, len(series) - 1)
                if smooth_ratio < 0.45:
                    continue
                scored.append({
                    'offset': s * 2,
                    'count': length,
                    'min': min(series),
                    'max': max(series),
                    'avg': round(sum(series) / len(series), 2),
                    'sample': series[:18],
                    'smooth_ratio': round(smooth_ratio, 3),
                    'series': series,
                })

            scored.sort(key=lambda r: (r['count'], r['smooth_ratio']), reverse=True)
            out[metric] = [{
                'offset': r['offset'],
                'count': r['count'],
                'min': r['min'],
                'max': r['max'],
                'avg': r['avg'],
                'sample': r['sample'],
                'smooth_ratio': r['smooth_ratio'],
            } for r in scored[:8]]

            if scored:
                # Keep best run for map overlay alignment.
                top = scored[0]
                best_series[metric] = {
                    'offset': top['offset'],
                    'count': top['count'],
                    'min': top['min'],
                    'max': top['max'],
                    'avg': top['avg'],
                    'series': top['series'][:8000],
                }
        return out, best_series

    kpi_candidates, metric_series = _scan_kpi_candidates(payload_slice)
    nemo_event_ref = _load_nemo_ff2_reference()
    nemo_object_ref = _load_nemo_object_mapper_summary()
    tag_reference = {}
    for tag in sorted(tag_counts.keys()):
        event_id = f'#{tag}'
        if event_id in nemo_event_ref:
            tag_reference[event_id] = nemo_event_ref[event_id]

    return {
        'size_bytes': len(data),
        'format_hint': 'NMFS container detected' if data.startswith(b'NMFS') else 'Unknown container',
        'header_ascii': ''.join(chr(x) if 32 <= x < 127 else '.' for x in data[:32]),
        'signature_hex': data[:16].hex(),
        'records_found': len(metadata_records),
        'records_preview': [r['raw'] for r in metadata_records[:120]],
        'record_tags': tag_counts,
        'record_offsets': metadata_records[:120],
        'payload_ascii_ratio': round(ascii_ratio, 4),
        'likely_encoded_payload': ascii_ratio < 0.2,
        'high_entropy_windows': high_entropy[:20],
        'entropy_windows_preview': entropy_windows[:20],
        'timestamp_candidates': timestamp_hits,
        'ascii_chunks_preview': all_ascii_lines[:40],
        'kpi_candidates': kpi_candidates,
        'metric_series': metric_series,
        'nemo_event_reference': tag_reference,
        'nemo_object_mapper_summary': nemo_object_ref,
    }


def _load_nemo_ff2_reference():
    """
    Read-only parser for Nemo FF2 documentation.
    Returns mapping: {"#FF": {"name": "File format", "params": [...]}, ...}
    """
    cached = _NEMO_REF_CACHE.get('ff2')
    if cached is not None:
        return cached
    out = {}
    if not os.path.exists(_NEMO_FF2_PATH):
        _NEMO_REF_CACHE['ff2'] = out
        return out
    try:
        with open(_NEMO_FF2_PATH, 'r', encoding='utf-8', errors='ignore') as f:
            html = f.read()
        # Pattern around the known FF2 event block:
        # <h2><a name="eventFF"></a>File format (#FF)</h2>
        event_blocks = re.finditer(
            r'<h2><a name="event[^"]*"></a>\s*(.*?)\s*\((#[A-Z0-9]+)\)\s*</h2>(.*?)(?=<h2><a name="event|$)',
            html,
            flags=re.S,
        )
        for m in event_blocks:
            event_name = unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()
            event_id = m.group(2).strip()
            block = m.group(3)
            params = []
            # Parameter names are typically in:
            # <td class="narrowShortName">RSRP</td>
            for p in re.finditer(r'<td class="narrowShortName">(.*?)</td>', block, flags=re.S):
                pname = unescape(re.sub(r'<[^>]+>', '', p.group(1))).strip()
                if pname and pname not in params:
                    params.append(pname)
                if len(params) >= 120:
                    break
            out[event_id] = {
                'name': event_name,
                'params': params[:40],
                'param_count': len(params),
            }
    except Exception:
        out = {}
    _NEMO_REF_CACHE['ff2'] = out
    return out


def _load_nemo_object_mapper_summary():
    """
    Read-only parser for object_mapper.xml.
    Returns small summary useful for NMFS context without touching Nemo files.
    """
    cached = _NEMO_REF_CACHE.get('object_mapper')
    if cached is not None:
        return cached
    summary = {
        'formats': [],
        'total_logs': 0,
        'technology_counts': {},
        'protocol_counts': {},
        'sample_logs': [],
    }
    if not os.path.exists(_NEMO_OBJECT_MAPPER_PATH):
        _NEMO_REF_CACHE['object_mapper'] = summary
        return summary
    try:
        root = parse_xml_file(_NEMO_OBJECT_MAPPER_PATH)
        formats = root.findall('.//format')
        summary['formats'] = [f.get('name') for f in formats if f.get('name')]
        sample_logs = []
        total_logs = 0
        tech_counts = {}
        proto_counts = {}
        for fmt in formats:
            for log in fmt.findall('.//log'):
                total_logs += 1
                tech = (log.get('technology') or '').strip()
                proto = (log.get('protocol') or '').strip()
                if tech:
                    tech_counts[tech] = tech_counts.get(tech, 0) + 1
                if proto:
                    proto_counts[proto] = proto_counts.get(proto, 0) + 1
                if len(sample_logs) < 25:
                    sample_logs.append({
                        'name': log.get('name'),
                        'hex': log.get('hex'),
                        'technology': tech or None,
                        'protocol': proto or None,
                        'objectname': log.get('objectname'),
                        'version': log.get('version'),
                    })
        summary['total_logs'] = total_logs
        summary['technology_counts'] = tech_counts
        summary['protocol_counts'] = proto_counts
        summary['sample_logs'] = sample_logs
    except Exception:
        pass
    _NEMO_REF_CACHE['object_mapper'] = summary
    return summary


@drive_test_viewer_bp.route('/drive-test-viewer')
@login_required
def page():
    _ensure_upload_dir()
    return render_template('drive_test_viewer.html', user=_format_user(_current_user()))


@drive_test_viewer_bp.route('/api/drive-test-viewer/upload', methods=['POST'])
@login_required
def upload():
    _ensure_upload_dir()
    gpx_file = request.files.get('gpx_file')
    nmfs_file = request.files.get('nmfs_file')

    if not gpx_file and not nmfs_file:
        return jsonify({'error': 'Upload at least one file (GPX or NMFS).'}), 400

    response = {'success': True}

    if gpx_file and gpx_file.filename:
        ext = os.path.splitext(gpx_file.filename)[1].lower()
        if ext not in _ALLOWED_GPX:
            return jsonify({'error': 'GPX file must have .gpx extension.'}), 400
        gpx_path, gpx_name = _save_upload(gpx_file, 'gpx')
        try:
            response['gpx'] = {'file_name': gpx_name, **_parse_gpx(gpx_path)}
        except Exception as e:
            return jsonify({'error': f'Failed to parse GPX: {e}'}), 400

    if nmfs_file and nmfs_file.filename:
        ext = os.path.splitext(nmfs_file.filename)[1].lower()
        if ext not in _ALLOWED_NMFS:
            return jsonify({'error': 'NMFS file must have .nmfs extension.'}), 400
        nmfs_path, nmfs_name = _save_upload(nmfs_file, 'nmfs')
        try:
            response['nmfs'] = {'file_name': nmfs_name, **_parse_nmfs(nmfs_path)}
        except Exception as e:
            return jsonify({'error': f'Failed to parse NMFS: {e}'}), 400

    return jsonify(response)
