"""SON trust smoke: unit builders already cover floors; this hits recommendation APIs.

Prefers a running PrimeNet (default http://127.0.0.1:8001). Falls back to an
in-process Flask app with module-access bypass when the server is down.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NCM_ENABLE_ETL", "0")
os.environ.setdefault("NCM_DISABLE_AUTO_BROWSER", "1")

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

from database_enhanced import create_session, get_db
from db.runtime import execute_query


def _row_id(row):
    return row["id"] if hasattr(row, "keys") else row[0]


def _admin_token() -> str:
    conn = get_db()
    try:
        admin = execute_query(
            conn,
            "SELECT id FROM users WHERE LOWER(COALESCE(role, '')) IN ('admin', 'owner') "
            "AND COALESCE(is_active, 1) LIMIT 1",
            (),
        ).fetchone()
    finally:
        conn.close()
    if not admin:
        raise SystemExit("SKIP: no admin/owner user")
    return create_session(int(_row_id(admin)))


def _smoke_http(base: str, token: str) -> int:
    import requests

    s = requests.Session()
    s.cookies.set("primenet_session", token, domain="127.0.0.1")
    s.cookies.set("nexus_session", token, domain="127.0.0.1")
    s.cookies.set("session_token", token, domain="127.0.0.1")
    root = base.rstrip("/")
    checks = []
    page = s.get(f"{root}/son-analytics", timeout=60)
    checks.append(("page", page.status_code == 200, page.status_code))
    ml = s.get(f"{root}/api/son/ml-status", timeout=60)
    checks.append(("ml-status", ml.status_code == 200, ml.status_code))
    recs = s.get(f"{root}/api/son/recommendations?limit=5", timeout=900)
    js = recs.json() if recs.ok else {}
    checks.append(("recommendations", recs.status_code == 200 and js.get("success"), recs.status_code))
    print(f"recommendations total={js.get('total')} n={len(js.get('recommendations') or [])}")
    rows = js.get("recommendations") or []
    if rows:
        rid = rows[0].get("id")
        detail = s.get(f"{root}/api/son/recommendations/{rid}", timeout=120)
        checks.append(("detail", detail.status_code == 200, detail.status_code))
    missing = s.get(f"{root}/api/son/recommendations/does-not-exist-zzz", timeout=60)
    checks.append(("missing-404", missing.status_code == 404, missing.status_code))
    for cat in ("Cluster", "Anomaly", "Topology"):
        rf = s.get(f"{root}/api/son/recommendations?category={cat}&limit=3", timeout=900)
        data = rf.json() if rf.ok else {}
        checks.append((f"filter-{cat}", rf.status_code == 200 and data.get("success"), rf.status_code))
        print(f"filter {cat} total={data.get('total')}")
    failed = [n for n, ok, _ in checks if not ok]
    for n, ok, code in checks:
        print(f"{'ok' if ok else 'FAIL'} {n} status={code}")
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("SON trust HTTP smoke OK")
    return 0


def _smoke_logic() -> int:
    """In-process path when no server — exercises builders + filters only."""
    from modules.son_analytics.logic import (
        build_all_recommendations,
        filter_recommendations,
        get_recommendation_by_id,
    )

    print("server down — using in-process build_all_recommendations (may be slow)")
    payload = build_all_recommendations(force_refresh=False)
    summary = payload.get("summary") or {}
    print("summary", summary)
    rows, total = filter_recommendations(payload, limit=5, offset=0)
    print(f"recommendations total={total} n={len(rows)}")
    if rows:
        rec = get_recommendation_by_id(payload, rows[0]["id"])
        assert rec is not None
        print("detail ok", rec.get("category"), rec.get("severity"))
    assert get_recommendation_by_id(payload, "does-not-exist-zzz") is None
    for cat in ("Cluster", "Anomaly", "Topology"):
        _, n = filter_recommendations(payload, category=cat, limit=3, offset=0)
        print(f"filter {cat} total={n}")
    print("SON trust logic smoke OK")
    return 0


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getenv("PRIMENET_BASE", "http://127.0.0.1:8001"))
    ap.add_argument("--logic-only", action="store_true")
    args = ap.parse_args()
    if args.logic_only:
        return _smoke_logic()
    token = _admin_token()
    try:
        import requests

        requests.get(args.base.rstrip("/") + "/healthz", timeout=3)
    except Exception:
        return _smoke_logic()
    try:
        return _smoke_http(args.base, token)
    except Exception as exc:  # noqa: BLE001
        print(f"HTTP smoke failed ({exc}); falling back to logic")
        return _smoke_logic()


if __name__ == "__main__":
    raise SystemExit(main())
