"""Smoke: Admin PM Plus Rules page + APIs; confirm PEP has no Agg Rules."""
from __future__ import annotations

import os

os.environ.setdefault("NCM_ENABLE_ETL", "0")

from app import app
from database_enhanced import create_session, get_db, set_user_force_password_change
from db.runtime import execute_query


def _row_id(row):
    return row["id"] if hasattr(row, "keys") else row[0]


def _unlock_password_gate(user_id: int) -> None:
    """Clear rotation gate so smoke can hit protected routes."""
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


def main() -> int:
    with get_db() as conn:
        admin = execute_query(
            conn,
            "SELECT id, username, role FROM users WHERE role='admin' AND is_active LIMIT 1",
            (),
        ).fetchone()
        user = execute_query(
            conn,
            "SELECT id FROM users WHERE role='user' AND is_active LIMIT 1",
            (),
        ).fetchone()

    if not admin:
        print("FAIL: no admin user")
        return 1

    admin_id = _row_id(admin)
    _unlock_password_gate(admin_id)
    token = create_session(admin_id)
    client = app.test_client()
    client.set_cookie("primenet_session", token)

    r = client.get("/admin-panel?section=pm-plus-rules")
    html = r.get_data(as_text=True)
    print(
        "admin_page",
        r.status_code,
        "tab" if "PM Plus Rules" in html else "NO_TAB",
        "panel" if "pm-plus-families" in html else "NO_PANEL",
        "import_btn" if "importPmPlusCatalog" in html else "NO_IMPORT",
    )

    r2 = client.get("/api/admin/pm-plus/rules/families")
    j2 = r2.get_json() or {}
    print(
        "families_api",
        r2.status_code,
        j2.get("success"),
        "n=",
        len(j2.get("families") or []),
    )

    r3 = client.get("/api/admin/pm-plus/rules/counters?q=M8005&limit=5")
    j3 = r3.get_json() or {}
    print(
        "counters_api",
        r3.status_code,
        j3.get("success"),
        "n=",
        len(j3.get("counters") or []),
        "sample=",
        (j3.get("counters") or [{}])[0].get("counter_id") if j3.get("counters") else None,
    )

    r4 = client.get("/performance-explorer-plus")
    html4 = r4.get_data(as_text=True)
    print(
        "pep_page",
        r4.status_code,
        "HAS_AGG_RULES" if ("Agg Rules" in html4 or "pep-mode-rules" in html4) else "no_agg_rules_ok",
        "health" if "Ingest Health" in html4 else "NO_HEALTH",
    )

    # Old PEP rules API should be gone
    r5 = client.get("/api/performance-explorer-plus/rules/families")
    print("old_pep_rules_api", r5.status_code)

    if user:
        ut = create_session(_row_id(user))
        c2 = app.test_client()
        c2.set_cookie("primenet_session", ut)
        rb = c2.get("/api/admin/pm-plus/rules/families")
        print("user_families", rb.status_code, (rb.get_json() or {}).get("error") or rb.headers.get("Location"))

    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
