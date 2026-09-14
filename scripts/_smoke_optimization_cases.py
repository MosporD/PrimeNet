"""Smoke test Optimization Cases core + routes registration."""
from __future__ import annotations

import os

os.environ.setdefault("NCM_ENABLE_ETL", "0")

from app import app
from core.cases import selection, service
from core.cases.schema import init_schema


def main() -> int:
    init_schema()
    case = service.open_case_from_issue(
        {
            "id": "smoke1",
            "module": "Change Impact",
            "category": "Configuration Impact",
            "title": "Smoke test case",
            "summary": "Local repo smoke",
            "score": 70,
            "severity": "High",
            "cells": ["SMOKE_CELL_A"],
            "vendor": "Nokia",
            "technology": "4G",
            "source_url": "/change-impact",
            "evidence": {"change": {"parameter": "tilt", "old_value": "2", "new_value": "4"}},
        },
        actor="smoke",
    )
    print("case_id", case["case_id"])
    print("state", case["state"])
    print("narrative_lines", len((case.get("narrative") or "").splitlines()))
    print("scorecard_status", (case.get("scorecard") or {}).get("status"))

    sel = selection.set_selection(
        "smoke", {"kind": "cells", "cells": ["SMOKE_CELL_A"], "source": "smoke"}
    )
    print("selection", sel["kind"], sel["cells"])

    client = app.test_client()
    r = client.get("/optimization-cases")
    print("page_status", r.status_code, "location", r.headers.get("Location"))
    rules = [rule.rule for rule in app.url_map.iter_rules()]
    print("has_page", "/optimization-cases" in rules)
    print("has_from_issue", any("/from-issue" in x for x in rules))
    print("has_selection", "/api/selection-context" in rules)
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
