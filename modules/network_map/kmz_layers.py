"""Per-user KMZ/KML reference layers for Network Map.

Stores uploaded files under DATA_ROOT/uploads/network_map_kmz/{user_id}/,
parses KML folders + placemarks into a tree + GeoJSON FeatureCollection,
and persists metadata/visibility in ncm_users.db (map_user_layers).
"""

from __future__ import annotations

import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

from database_enhanced import get_db
from db.runtime import execute_query
from sync_config import DATA_ROOT
from werkzeug.utils import secure_filename

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_LAYERS_PER_USER = 20
ALLOWED_EXT = {'.kmz', '.kml'}

# Elements we skip (v1 = vectors only)
_SKIP_TAGS = frozenset({
    'GroundOverlay', 'NetworkLink', 'Model', 'PhotoOverlay', 'ScreenOverlay',
})

_KML_NS = {
    'kml': 'http://www.opengis.net/kml/2.2',
    'gx': 'http://www.google.com/kml/ext/2.2',
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def layers_root() -> str:
    return os.path.join(DATA_ROOT, 'uploads', 'network_map_kmz')


def user_dir(user_id: int) -> str:
    path = os.path.join(layers_root(), str(int(user_id)))
    os.makedirs(path, exist_ok=True)
    return path


def ensure_schema(conn=None) -> None:
    own = conn is None
    if own:
        conn = get_db()
    execute_query(conn, '''
        CREATE TABLE IF NOT EXISTS map_user_layers (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            tree_json TEXT NOT NULL,
            geojson_path TEXT NOT NULL,
            visibility_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    execute_query(
        conn,
        'CREATE INDEX IF NOT EXISTS idx_map_user_layers_user '
        'ON map_user_layers(user_id)',
    )
    if own:
        conn.commit()
        conn.close()


def _local_tag(tag: str) -> str:
    if '}' in tag:
        return tag.rsplit('}', 1)[-1]
    return tag


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _local_tag(c.tag) == name:
            return c
    return None


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local_tag(c.tag) == name]


def _text(el: ET.Element | None, default: str = '') -> str:
    if el is None or el.text is None:
        return default
    return (el.text or '').strip() or default


def _parse_coords(text: str) -> list[list[float]]:
    """Parse KML coordinate string → list of [lng, lat] (ignore altitude)."""
    out: list[list[float]] = []
    if not text:
        return out
    for token in re.split(r'\s+', text.strip()):
        if not token:
            continue
        parts = token.split(',')
        if len(parts) < 2:
            continue
        try:
            lng = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            continue
        out.append([lng, lat])
    return out


def _geometry_from_element(el: ET.Element) -> dict | None:
    tag = _local_tag(el.tag)

    if tag == 'Point':
        coords = _parse_coords(_text(_child(el, 'coordinates')))
        if not coords:
            return None
        return {'type': 'Point', 'coordinates': coords[0]}

    if tag == 'LineString':
        coords = _parse_coords(_text(_child(el, 'coordinates')))
        if len(coords) < 2:
            return None
        return {'type': 'LineString', 'coordinates': coords}

    if tag == 'LinearRing':
        coords = _parse_coords(_text(_child(el, 'coordinates')))
        if len(coords) < 3:
            return None
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        return {'type': 'LineString', 'coordinates': coords}

    if tag == 'Polygon':
        outer = _child(el, 'outerBoundaryIs')
        ring_el = _child(outer, 'LinearRing') if outer is not None else None
        if ring_el is None:
            ring_el = _child(el, 'LinearRing')
        outer_coords = _parse_coords(_text(_child(ring_el, 'coordinates'))) if ring_el is not None else []
        if len(outer_coords) < 3:
            return None
        if outer_coords[0] != outer_coords[-1]:
            outer_coords.append(outer_coords[0])
        rings = [outer_coords]
        for inner in _children(el, 'innerBoundaryIs'):
            ir = _child(inner, 'LinearRing')
            ic = _parse_coords(_text(_child(ir, 'coordinates'))) if ir is not None else []
            if len(ic) >= 3:
                if ic[0] != ic[-1]:
                    ic.append(ic[0])
                rings.append(ic)
        return {'type': 'Polygon', 'coordinates': rings}

    if tag in ('MultiGeometry', 'MultiTrack') or tag.endswith('MultiTrack'):
        geoms = []
        for child in el:
            g = _geometry_from_element(child)
            if g:
                geoms.append(g)
        if not geoms:
            return None
        if len(geoms) == 1:
            return geoms[0]
        types = {g['type'] for g in geoms}
        if types == {'Point'}:
            return {'type': 'MultiPoint', 'coordinates': [g['coordinates'] for g in geoms]}
        if types == {'LineString'}:
            return {'type': 'MultiLineString', 'coordinates': [g['coordinates'] for g in geoms]}
        if types == {'Polygon'}:
            return {'type': 'MultiPolygon', 'coordinates': [g['coordinates'] for g in geoms]}
        return {'type': 'GeometryCollection', 'geometries': geoms}

    # Look for nested geometry
    for child in el:
        if _local_tag(child.tag) in (
            'Point', 'LineString', 'Polygon', 'MultiGeometry', 'LinearRing',
        ):
            g = _geometry_from_element(child)
            if g:
                return g
    return None


def _placemark_geometry(pm: ET.Element) -> dict | None:
    for child in pm:
        tag = _local_tag(child.tag)
        if tag in ('Point', 'LineString', 'Polygon', 'MultiGeometry', 'LinearRing'):
            return _geometry_from_element(child)
        if tag == 'MultiTrack' or tag.endswith('MultiTrack'):
            return _geometry_from_element(child)
    return None


def _strip_html(text: str) -> str:
    """Lightweight description sanitizer for popups (no raw HTML)."""
    if not text:
        return ''
    # CDATA / HTML → plain-ish text
    t = re.sub(r'(?is)<br\s*/?>', '\n', text)
    t = re.sub(r'(?is)<[^>]+>', '', t)
    t = re.sub(r'[ \t]+\n', '\n', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()[:2000]


def _new_id(prefix: str = 'n') -> str:
    return f'{prefix}_{uuid.uuid4().hex[:10]}'


def _walk_container(
    el: ET.Element,
    parent_id: str | None,
    tree_nodes: list[dict],
    features: list[dict],
    visibility: dict[str, bool],
    warnings: list[str],
    seen_skip: set[str],
) -> None:
    """Walk Folder/Document children; build tree + GeoJSON features."""
    for child in el:
        tag = _local_tag(child.tag)

        if tag in _SKIP_TAGS:
            if tag not in seen_skip:
                warnings.append(f'{tag} elements were skipped (vectors only)')
                seen_skip.add(tag)
            continue

        if tag in ('Folder', 'Document'):
            node_id = _new_id('f')
            name = _text(_child(child, 'name'), tag)
            tree_nodes.append({
                'id': node_id,
                'parent_id': parent_id,
                'name': name,
                'type': 'folder',
            })
            visibility[node_id] = True
            _walk_container(
                child, node_id, tree_nodes, features, visibility, warnings, seen_skip,
            )
            continue

        if tag == 'Placemark':
            node_id = _new_id('p')
            name = _text(_child(child, 'name'), 'Placemark')
            desc = _strip_html(_text(_child(child, 'description')))
            geom = _placemark_geometry(child)
            tree_nodes.append({
                'id': node_id,
                'parent_id': parent_id,
                'name': name,
                'type': 'placemark',
                'has_geometry': geom is not None,
            })
            visibility[node_id] = True
            if geom is not None:
                features.append({
                    'type': 'Feature',
                    'id': node_id,
                    'geometry': geom,
                    'properties': {
                        'id': node_id,
                        'folder_id': node_id,
                        'parent_id': parent_id,
                        'name': name,
                        'description': desc,
                    },
                })
            continue

        # Style / Schema / ExtendedData / etc. — ignore
        if tag in ('name', 'description', 'visibility', 'open', 'Snippet',
                   'Style', 'StyleMap', 'Schema', 'ExtendedData', 'TimeSpan',
                   'TimeStamp', 'region', 'Region', 'LookAt', 'Camera',
                   'atom:author', 'atom:link', 'address', 'phoneNumber'):
            continue


def parse_kml_bytes(kml_bytes: bytes, display_name: str) -> dict[str, Any]:
    """Parse KML XML → tree nodes, FeatureCollection, default visibility, warnings."""
    # Drop XML namespaces so local tags are plain (KML often uses default ns)
    text = kml_bytes.decode('utf-8', errors='replace')
    # Keep content; ElementTree still gets clark notation — we use _local_tag
    try:
        root = ET.fromstring(text.encode('utf-8'))
    except ET.ParseError as e:
        raise ValueError(f'Invalid KML XML: {e}') from e

    tree_nodes: list[dict] = []
    features: list[dict] = []
    visibility: dict[str, bool] = {}
    warnings: list[str] = []
    seen_skip: set[str] = set()

    root_tag = _local_tag(root.tag)
    # kml → Document/Folder, or Document as root
    containers: list[ET.Element] = []
    if root_tag == 'kml':
        for c in root:
            ct = _local_tag(c.tag)
            if ct in ('Document', 'Folder'):
                containers.append(c)
            elif ct == 'Placemark':
                # Rare: placemarks directly under kml
                containers.append(root)
                break
        if not containers:
            containers = [root]
    elif root_tag in ('Document', 'Folder'):
        containers = [root]
    else:
        containers = [root]

    # Single synthetic root folder for the file
    root_id = _new_id('f')
    doc_name = display_name
    for cont in containers:
        n = _text(_child(cont, 'name'))
        if n:
            doc_name = n
            break

    tree_nodes.append({
        'id': root_id,
        'parent_id': None,
        'name': doc_name,
        'type': 'folder',
    })
    visibility[root_id] = True

    for cont in containers:
        # If the container IS Document/Folder, walk its children under root_id
        # (don't create a duplicate folder for the same Document)
        if _local_tag(cont.tag) in ('Document', 'Folder') and cont is not root:
            # Children of this document go under our synthetic root
            _walk_container(
                cont, root_id, tree_nodes, features, visibility, warnings, seen_skip,
            )
        else:
            _walk_container(
                cont, root_id, tree_nodes, features, visibility, warnings, seen_skip,
            )

    # Nest tree for API convenience
    nested = _nest_tree(tree_nodes)

    return {
        'name': doc_name,
        'tree': nested,
        'tree_flat': tree_nodes,
        'geojson': {
            'type': 'FeatureCollection',
            'features': features,
        },
        'visibility': visibility,
        'warnings': warnings,
        'feature_count': len(features),
    }


def _nest_tree(flat: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for n in flat:
        by_id[n['id']] = {
            'id': n['id'],
            'name': n['name'],
            'type': n['type'],
            'has_geometry': n.get('has_geometry'),
            'children': [],
        }
    roots: list[dict] = []
    for n in flat:
        node = by_id[n['id']]
        pid = n.get('parent_id')
        if pid and pid in by_id:
            by_id[pid]['children'].append(node)
        else:
            roots.append(node)
    return roots


def extract_kml_from_upload(file_path: str, ext: str) -> tuple[bytes, list[str]]:
    """Return (kml_bytes, warnings). For .kml reads file; for .kmz finds first .kml in zip."""
    warnings: list[str] = []
    if ext == '.kml':
        with open(file_path, 'rb') as f:
            return f.read(), warnings

    if not zipfile.is_zipfile(file_path):
        raise ValueError('KMZ file is not a valid ZIP archive')

    with zipfile.ZipFile(file_path, 'r') as zf:
        kml_names = [
            n for n in zf.namelist()
            if n.lower().endswith('.kml') and not n.startswith('__MACOSX')
        ]
        if not kml_names:
            raise ValueError('KMZ contains no KML file')
        # Prefer doc.kml / top-level
        kml_names.sort(key=lambda n: (0 if os.path.basename(n).lower() == 'doc.kml' else 1,
                                      n.count('/'), n.lower()))
        chosen = kml_names[0]
        if len(kml_names) > 1:
            warnings.append(f'Multiple KML files in KMZ; using {chosen}')
        return zf.read(chosen), warnings


def count_user_layers(user_id: int) -> int:
    ensure_schema()
    conn = get_db()
    row = execute_query(
        conn,
        'SELECT COUNT(*) AS c FROM map_user_layers WHERE user_id = ?',
        (user_id,),
    ).fetchone()
    conn.close()
    return int(row['c'] if row and 'c' in row.keys() else (row[0] if row else 0))


def list_layers(user_id: int) -> list[dict]:
    ensure_schema()
    conn = get_db()
    rows = execute_query(conn, '''
        SELECT id, user_id, name, original_filename, tree_json, visibility_json,
               created_at, updated_at
        FROM map_user_layers
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user_id,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            tree = json.loads(r['tree_json'] or '[]')
        except Exception:
            tree = []
        try:
            visibility = json.loads(r['visibility_json'] or '{}')
        except Exception:
            visibility = {}
        out.append({
            'id': r['id'],
            'name': r['name'],
            'original_filename': r['original_filename'],
            'tree': tree,
            'visibility': visibility,
            'created_at': r['created_at'],
            'updated_at': r['updated_at'],
        })
    return out


def get_layer_row(layer_id: str, user_id: int):
    ensure_schema()
    conn = get_db()
    row = execute_query(conn, '''
        SELECT * FROM map_user_layers WHERE id = ? AND user_id = ?
    ''', (layer_id, user_id)).fetchone()
    conn.close()
    return row


def load_geojson(layer_id: str, user_id: int) -> dict | None:
    row = get_layer_row(layer_id, user_id)
    if not row:
        return None
    path = row['geojson_path']
    if not path or not os.path.isfile(path):
        return {'type': 'FeatureCollection', 'features': []}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_visibility(layer_id: str, user_id: int, visibility: dict) -> bool:
    row = get_layer_row(layer_id, user_id)
    if not row:
        return False
    conn = get_db()
    execute_query(conn, '''
        UPDATE map_user_layers
        SET visibility_json = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
    ''', (json.dumps(visibility), _utc_now(), layer_id, user_id))
    conn.commit()
    conn.close()
    return True


def delete_layer(layer_id: str, user_id: int) -> bool:
    row = get_layer_row(layer_id, user_id)
    if not row:
        return False
    for p in (row['stored_path'], row['geojson_path']):
        try:
            if p and os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
    conn = get_db()
    execute_query(
        conn,
        'DELETE FROM map_user_layers WHERE id = ? AND user_id = ?',
        (layer_id, user_id),
    )
    conn.commit()
    conn.close()
    return True


def create_layer_from_upload(
    user_id: int,
    file_storage,
) -> dict[str, Any]:
    """Save upload, parse, persist. Returns layer summary + warnings.

    Raises ValueError on validation / parse errors.
    """
    if not file_storage or not file_storage.filename:
        raise ValueError('No file uploaded')

    raw_name = file_storage.filename
    safe = secure_filename(raw_name) or 'layer.kml'
    ext = os.path.splitext(safe)[1].lower()
    if ext not in ALLOWED_EXT:
        raise ValueError('Only .kmz and .kml files are allowed')

    if count_user_layers(user_id) >= MAX_LAYERS_PER_USER:
        raise ValueError(f'Maximum of {MAX_LAYERS_PER_USER} layers per user')

    # Spool to disk with size check
    layer_id = uuid.uuid4().hex[:12]
    dest_dir = user_dir(user_id)
    stored_name = f'{layer_id}{ext}'
    stored_path = os.path.join(dest_dir, stored_name)

    total = 0
    with open(stored_path, 'wb') as out:
        while True:
            chunk = file_storage.stream.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                out.close()
                try:
                    os.remove(stored_path)
                except OSError:
                    pass
                raise ValueError(f'File exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB limit')
            out.write(chunk)

    try:
        kml_bytes, extract_warnings = extract_kml_from_upload(stored_path, ext)
        display = os.path.splitext(safe)[0] or 'Layer'
        parsed = parse_kml_bytes(kml_bytes, display)
    except Exception:
        try:
            os.remove(stored_path)
        except OSError:
            pass
        raise

    geojson_path = os.path.join(dest_dir, f'{layer_id}.geojson')
    with open(geojson_path, 'w', encoding='utf-8') as f:
        json.dump(parsed['geojson'], f, ensure_ascii=False, separators=(',', ':'))

    warnings = list(extract_warnings) + list(parsed.get('warnings') or [])
    now = _utc_now()

    ensure_schema()
    conn = get_db()
    execute_query(conn, '''
        INSERT INTO map_user_layers (
            id, user_id, name, original_filename, stored_path,
            tree_json, geojson_path, visibility_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        layer_id,
        user_id,
        parsed['name'],
        safe,
        stored_path,
        json.dumps(parsed['tree']),
        geojson_path,
        json.dumps(parsed['visibility']),
        now,
        now,
    ))
    conn.commit()
    conn.close()

    return {
        'id': layer_id,
        'name': parsed['name'],
        'original_filename': safe,
        'tree': parsed['tree'],
        'visibility': parsed['visibility'],
        'feature_count': parsed['feature_count'],
        'warnings': warnings,
        'created_at': now,
        'updated_at': now,
    }
