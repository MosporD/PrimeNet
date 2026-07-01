"""Backfill cached Jordan elevations for all known site coordinates."""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.elevation import coord_key, elevation_for_points, is_in_jordan, normalize_coord
from db.runtime import connect_metadata


def load_site_points(limit: int | None = None) -> list[tuple[float, float]]:
    conn = connect_metadata()
    try:
        conn.row_factory = None
        sql = """
            SELECT DISTINCT latitude, longitude
            FROM sites
            WHERE latitude IS NOT NULL
              AND longitude IS NOT NULL
        """
        if limit:
            sql += " LIMIT ?"
            rows = conn.execute(sql, (int(limit),)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    points: list[tuple[float, float]] = []
    seen: set[str] = set()
    for lat, lng in rows:
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
        points.append((lat_f, lng_f))
    return points


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Jordan elevation cache from metadata site coordinates.")
    parser.add_argument("--limit", type=int, default=0, help="Limit coordinates for a smoke run.")
    parser.add_argument("--batch-size", type=int, default=500, help="Coordinates to resolve per local batch.")
    args = parser.parse_args()

    points = load_site_points(args.limit or None)
    print(f"[elevation] loaded {len(points):,} distinct Jordan site coordinate(s)")
    if not points:
        return 0

    resolved = 0
    unavailable = 0
    batch_size = max(1, int(args.batch_size or 500))
    for start in range(0, len(points), batch_size):
        batch = points[start : start + batch_size]
        result = elevation_for_points(batch)
        resolved += sum(1 for v in result.values() if v is not None)
        unavailable += sum(1 for v in result.values() if v is None)
        print(
            f"[elevation] batch {start + 1:,}-{start + len(batch):,}: "
            f"resolved={resolved:,} unavailable={unavailable:,}"
        )

    print(f"[elevation] done resolved={resolved:,} unavailable={unavailable:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
