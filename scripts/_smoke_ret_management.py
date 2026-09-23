"""Smoke RET Management page + Nokia/Huawei APIs against a running PrimeNet.

Checks:
  - /ret-management HTML loads three.js + hologram scripts
  - static assets (vendor/three.min.js, ret_hologram.js) return 200
  - NE lists for nokia / huawei
  - site-layout returns multiple sectors with distinct azimuths
  - live RET fetch (when CM creds work) has parseable _ret_sector
  - sector keys join metadata layout keys (UI hologram join)

Usage (PrimeNet already on :8001):
  python scripts/_smoke_ret_management.py
  python scripts/_smoke_ret_management.py --base http://127.0.0.1:8001
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

os.environ.setdefault("NCM_ENABLE_ETL", "0")
os.environ.setdefault("NCM_DISABLE_AUTO_BROWSER", "1")
os.environ.setdefault("NCM_DISABLE_LIVE_LOGGER_TERMINAL", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

import requests

from database_enhanced import create_session, get_db, set_user_force_password_change
from db.runtime import execute_query


def _row_id(row):
    return row["id"] if hasattr(row, "keys") else row[0]


def _unlock(user_id: int) -> None:
    from datetime import datetime

    set_user_force_password_change(user_id, False)
    conn = get_db()
    try:
        execute_query(
            conn,
            "UPDATE users SET password_changed_at = ?, force_password_change = 0 WHERE id = ?",
            (datetime.now(), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def _session(base: str) -> requests.Session:
    with get_db() as conn:
        admin = execute_query(
            conn,
            "SELECT id, username FROM users WHERE role='admin' AND is_active LIMIT 1",
            (),
        ).fetchone()
    if not admin:
        raise SystemExit("FAIL: no admin user in PrimeNet users DB")
    user_id = _row_id(admin)
    _unlock(user_id)
    token = create_session(user_id)
    s = requests.Session()
    s.cookies.set("primenet_session", token, domain="127.0.0.1")
    s.headers["Accept"] = "application/json, text/html"
    s.base = base.rstrip("/")
    print(f"session ok user_id={user_id}")
    return s


def _get(s: requests.Session, path: str, **params):
    url = f"{s.base}{path}"
    if params:
        url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None and v != ''})}"
    r = s.get(url, timeout=120, allow_redirects=False)
    return r


def _check_page(s: requests.Session) -> None:
    r = _get(s, "/ret-management")
    if r.status_code in (301, 302):
        print("FAIL page redirect", r.status_code, r.headers.get("Location"))
        raise SystemExit(2)
    html = r.text
    checks = {
        "status": r.status_code == 200,
        "title": "RET Management" in html,
        "three": "vendor/three.min.js" in html,
        "hologram": "ret_hologram.js" in html,
        "pitch30": 'id="holo-pitch"' in html and 'value="30"' in html,
        "canvas": 'id="holo-canvas"' in html,
    }
    print("page", " ".join(f"{k}={'OK' if v else 'FAIL'}" for k, v in checks.items()))
    if not all(checks.values()):
        raise SystemExit(3)

    for asset in (
        "/ret-management/static/vendor/three.min.js?v=0.160.0",
        "/ret-management/static/ret_hologram.js?v=2.0",
        "/ret-management/static/ret_management.js?v=1.18",
    ):
        ar = _get(s, asset.split("?")[0])
        # query stripped — flask ignores unknown qs; hit with qs too
        ar2 = s.get(f"{s.base}{asset}", timeout=60)
        ok = ar2.status_code == 200 and len(ar2.content) > 500
        print(f"asset {asset.split('/')[-1].split('?')[0]} {ar2.status_code} bytes={len(ar2.content)} {'OK' if ok else 'FAIL'}")
        if not ok:
            raise SystemExit(4)


def _pick_ne(items: list[dict], *, prefer_ids: tuple[str, ...] = ()) -> dict | None:
    if not items:
        return None
    for pref in prefer_ids:
        for item in items:
            sid = str(item.get("site_id") or "")
            mid = str(item.get("metadata_site_id") or "")
            if sid == pref or mid == pref or sid.endswith(pref) or mid.endswith(pref):
                return item
    return items[0]


def _smoke_vendor(s: requests.Session, vendor: str, prefer_ids: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    q = prefer_ids[0] if prefer_ids else ""
    r = _get(s, "/api/ret-management/nes", vendor=vendor, limit=80, q=q)
    if r.status_code != 200:
        print(f"nes[{vendor}] FAIL", r.status_code, r.text[:200])
        return [f"{vendor}: NE list {r.status_code}"]
    body = r.json()
    items = body.get("items") or []
    print(f"nes[{vendor}]", "n=", len(items), "q=", q or "(none)", "ok=", body.get("success"))
    if not items:
        # broaden search if preferred id not in catalog spelling
        r = _get(s, "/api/ret-management/nes", vendor=vendor, limit=80)
        body = r.json()
        items = body.get("items") or []
        print(f"nes[{vendor}] broadened n=", len(items))
    if not items:
        return [f"{vendor}: empty NE list"]

    ne = _pick_ne(items, prefer_ids=prefer_ids)
    assert ne is not None
    site_id = str(ne.get("site_id") or "").strip()
    meta_id = str(ne.get("metadata_site_id") or "").strip()
    ne_name = str(ne.get("ne_name") or ne.get("name") or "").strip()
    print(f"picked[{vendor}]", "site_id=", site_id, "metadata_site_id=", meta_id, "ne=", ne_name[:60])

    lr = _get(
        s,
        "/api/ret-management/site-layout",
        vendor=vendor,
        site_id=site_id,
        metadata_site_id=meta_id,
        ne_name=ne_name,
        site_name=ne.get("site_name") or "",
    )
    if lr.status_code != 200:
        print(f"layout[{vendor}] FAIL", lr.status_code, lr.text[:240])
        problems.append(f"{vendor}: site-layout {lr.status_code}")
        layout = {}
    else:
        layout = lr.json()
        problems.extend(_layout_ok(layout, vendor))

    if vendor == "nokia":
        rr = _get(s, "/api/ret-management/nokia/retu", site_id=site_id or meta_id)
    else:
        rr = _get(
            s,
            "/api/ret-management/huawei/rets",
            site_id=site_id or meta_id,
            ne_name=ne_name,
        )
    if rr.status_code != 200:
        err = ""
        try:
            err = (rr.json() or {}).get("error") or rr.text[:160]
        except Exception:
            err = rr.text[:160]
        print(f"rets[{vendor}] HTTP {rr.status_code}: {err}")
        problems.append(f"{vendor}: RET fetch {rr.status_code} ({err[:120]})")
        return problems

    payload = rr.json()
    rows = payload.get("rows") or []
    print(
        f"rets[{vendor}] http_ok",
        "warnings=", len(payload.get("warnings") or []),
        "cred=", payload.get("credential_source") or "",
        "notice=", (payload.get("credential_notice") or "")[:80],
    )
    problems.extend(_ret_join_report(vendor, rows, layout))
    return problems


def _layout_ok(layout: dict, label: str) -> list[str]:
    sectors = layout.get("sectors") or []
    keys = [str(s.get("key")) for s in sectors]
    azs = [s.get("azimuth") for s in sectors if s.get("azimuth") is not None]
    uniq_az = len({round(float(a), 1) for a in azs})
    print(
        f"layout[{label}]",
        "sectors=", len(sectors),
        "keys=", keys[:8],
        "az=", [round(float(a), 1) for a in azs[:8]],
        "warnings=", len(layout.get("warnings") or []),
    )
    problems = []
    if len(sectors) < 2:
        problems.append(f"{label}: expected >=2 sectors, got {len(sectors)}")
    if any(k.isdigit() and int(k) > 26 for k in keys):
        problems.append(f"{label}: sector keys look like site ids: {keys[:5]}")
    if len(sectors) >= 2 and uniq_az < 2:
        problems.append(f"{label}: sectors collapsed to one azimuth ({azs[:3]})")
    return problems


def _ret_join_report(vendor: str, rows: list[dict], layout: dict) -> list[str]:
    layout_keys = {str(s.get("key")) for s in (layout.get("sectors") or [])}
    sectors = Counter(str(r.get("_ret_sector") or "") for r in rows)
    mapped = sum(1 for r in rows if r.get("_ret_sector") and str(r.get("_ret_sector")) in layout_keys)
    unmapped = sum(1 for r in rows if not r.get("_ret_sector"))
    orphan = sum(
        1
        for r in rows
        if r.get("_ret_sector") and str(r.get("_ret_sector")) not in layout_keys
    )
    samples = []
    for r in rows[:5]:
        if vendor == "huawei":
            name = r.get("Subunit Name") or r.get("SubunitName") or ""
            samples.append(f"{name}->{r.get('_ret_sector')!r}")
        else:
            samples.append(f"{r.get('sectorID')}->{r.get('_ret_sector')!r}")
    print(
        f"rets[{vendor}]",
        "n=", len(rows),
        "sector_hist=", dict(sectors.most_common(8)),
        "mapped=", mapped,
        "unmapped=", unmapped,
        "orphan=", orphan,
        "samples=", samples,
    )
    problems = []
    if not rows:
        problems.append(f"{vendor}: no RET rows")
    elif mapped == 0 and layout_keys:
        problems.append(f"{vendor}: zero RET sectors joined to layout keys {sorted(layout_keys)[:6]}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("PRIMENET_BASE", "http://127.0.0.1:8001"))
    parser.add_argument("--nokia-site", default="1003")
    parser.add_argument("--huawei-site", default="1020")
    args = parser.parse_args()

    # Health
    h = requests.get(f"{args.base.rstrip('/')}/health/live", timeout=5)
    print("health", h.status_code, h.text.strip())
    if h.status_code != 200:
        print("FAIL: PrimeNet not reachable — start primenet_app.py on 8001")
        return 1

    s = _session(args.base)
    _check_page(s)

    defaults = _get(s, "/api/ret-management/defaults")
    print("defaults", defaults.status_code, (defaults.json() if defaults.status_code == 200 else defaults.text[:120]))

    problems: list[str] = []
    problems.extend(_smoke_vendor(s, "nokia", prefer_ids=(args.nokia_site,)))
    problems.extend(_smoke_vendor(s, "huawei", prefer_ids=(args.huawei_site,)))

    print("---")
    if problems:
        print("SMOKE ISSUES:")
        for p in problems:
            print(" -", p)
        # Layout/UI asset failures already exited. CM reachability issues = exit 5 (soft).
        cm_only = all("RET fetch" in p or "no RET rows" in p for p in problems)
        return 5 if cm_only else 6

    print("SMOKE OK: UI assets + site-layout + RET sector join for nokia & huawei")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
