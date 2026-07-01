"""Shared Jordan elevation lookup with persistent SQLite caching."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Iterable

from sync_config import DATABASES_ROOT

JORDAN_BOUNDS = {
    "min_lat": 29.0,
    "max_lat": 33.6,
    "min_lng": 34.7,
    "max_lng": 39.4,
}

ELEVATION_DB = os.path.join(DATABASES_ROOT, "geo", "elevation_cache.db")
_DB_LOCK = threading.Lock()


def coord_key(lat: float, lng: float) -> str:
    return f"{float(lat):.5f},{float(lng):.5f}"


def normalize_coord(lat: object, lng: object) -> tuple[float, float] | None:
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
        return None
    return lat_f, lng_f


def is_in_jordan(lat: float, lng: float) -> bool:
    return (
        JORDAN_BOUNDS["min_lat"] <= lat <= JORDAN_BOUNDS["max_lat"]
        and JORDAN_BOUNDS["min_lng"] <= lng <= JORDAN_BOUNDS["max_lng"]
    )


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(ELEVATION_DB), exist_ok=True)
    conn = sqlite3.connect(ELEVATION_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS elevation_cache (
            coord_key TEXT PRIMARY KEY,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            elevation_m REAL,
            source TEXT NOT NULL DEFAULT 'open-meteo',
            resolution_key TEXT NOT NULL DEFAULT '5dp',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_elevation_cache_lat_lng ON elevation_cache(lat, lng)")
    conn.commit()
    return conn


def _unique_points(points: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    seen: set[str] = set()
    for lat, lng in points:
        norm = normalize_coord(lat, lng)
        if not norm:
            continue
        lat_f, lng_f = norm
        if not is_in_jordan(lat_f, lng_f):
            continue
        key = coord_key(lat_f, lng_f)
        if key in seen:
            continue
        seen.add(key)
        out.append((lat_f, lng_f))
    return out


def _fetch_open_meteo(points: list[tuple[float, float]]) -> dict[str, float | None]:
    if not points:
        return {}
    out: dict[str, float | None] = {}
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        params = urllib.parse.urlencode(
            {
                "latitude": ",".join(f"{lat:.6f}" for lat, _lng in batch),
                "longitude": ",".join(f"{lng:.6f}" for _lat, lng in batch),
            }
        )
        url = f"https://api.open-meteo.com/v1/elevation?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PrimeNet/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
            elevations = payload.get("elevation") if isinstance(payload, dict) else None
            if not isinstance(elevations, list):
                elevations = []
            for idx, (lat, lng) in enumerate(batch):
                value = elevations[idx] if idx < len(elevations) else None
                try:
                    out[coord_key(lat, lng)] = round(float(value), 1) if value is not None else None
                except (TypeError, ValueError):
                    out[coord_key(lat, lng)] = None
        except Exception:
            for lat, lng in batch:
                out[coord_key(lat, lng)] = None
    return out


def elevation_for_points(points: Iterable[tuple[float, float]], *, fetch_missing: bool = True) -> dict[str, float | None]:
    unique = _unique_points(points)
    if not unique:
        return {}

    with _DB_LOCK:
        conn = _connect()
        try:
            cached: dict[str, float | None] = {}
            misses: list[tuple[float, float]] = []
            for lat, lng in unique:
                key = coord_key(lat, lng)
                row = conn.execute("SELECT elevation_m FROM elevation_cache WHERE coord_key = ?", (key,)).fetchone()
                if row is None:
                    misses.append((lat, lng))
                else:
                    cached[key] = row["elevation_m"]

            if fetch_missing and misses:
                fetched = _fetch_open_meteo(misses)
                now = datetime.now(timezone.utc).isoformat()
                for lat, lng in misses:
                    key = coord_key(lat, lng)
                    elev = fetched.get(key)
                    cached[key] = elev
                    existing = conn.execute(
                        "SELECT created_at FROM elevation_cache WHERE coord_key = ?",
                        (key,),
                    ).fetchone()
                    created_at = existing["created_at"] if existing else now
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO elevation_cache
                            (coord_key, lat, lng, elevation_m, source, resolution_key, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (key, lat, lng, elev, "open-meteo", "5dp", created_at, now),
                    )
                conn.commit()
            else:
                for lat, lng in misses:
                    cached[coord_key(lat, lng)] = None
            return cached
        finally:
            conn.close()


def elevation_for_point(lat: object, lng: object, *, fetch_missing: bool = True) -> float | None:
    norm = normalize_coord(lat, lng)
    if not norm:
        return None
    lat_f, lng_f = norm
    if not is_in_jordan(lat_f, lng_f):
        return None
    return elevation_for_points([(lat_f, lng_f)], fetch_missing=fetch_missing).get(coord_key(lat_f, lng_f))
