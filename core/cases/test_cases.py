"""Unit tests for core.cases (no live PM/CM required)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class CasesCoreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        cases_dir = root / "cases"
        cases_dir.mkdir()
        self._patches = [
            mock.patch("core.cases.config.CASES_DIR", cases_dir),
            mock.patch("core.cases.config.SQLITE_PATH", cases_dir / "optimization_cases.db"),
        ]
        for p in self._patches:
            p.start()
        from core.cases.schema import init_schema

        init_schema()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()

    def test_create_transition_and_list(self):
        from core.cases import store

        case = store.create_case(
            {
                "title": "Test overshoot",
                "summary": "PD far",
                "cells": ["CELL_A", "CELL_B"],
                "severity": "High",
                "score": 72,
                "source_module": "Overshooting Detector",
            },
            actor="malek",
        )
        self.assertTrue(case["case_id"])
        self.assertEqual(case["state"], "open")
        self.assertEqual(case["cells"], ["CELL_A", "CELL_B"])
        self.assertEqual(case["owner"], "malek")

        assigned = store.transition_case(case["case_id"], "assigned", actor="malek", note="taking it")
        self.assertEqual(assigned["state"], "assigned")

        with self.assertRaises(store.CaseError):
            store.transition_case(case["case_id"], "executed", actor="malek")

        rows = store.list_cases(state="assigned")
        self.assertEqual(len(rows), 1)
        events = store.list_events(case["case_id"])
        types = [e["event_type"] for e in events]
        self.assertIn("created", types)
        self.assertIn("transition", types)

    def test_narrative_and_scorecard(self):
        from core.cases.correlator import build_narrative
        from core.cases.scorecard import build_scorecard

        facts = [
            {"type": "pm_degradation", "verified": True, "cell": "A", "category": "Accessibility", "change_pct": -12},
            {"type": "cm_change", "verified": True, "cell": "A", "parameter": "tilt", "old_value": "2", "new_value": "6"},
        ]
        text = build_narrative(facts, cells=["A"], title="Impact check")
        self.assertIn("PM:", text)
        self.assertIn("CM:", text)
        self.assertIn("change-impact", text.lower())

        card = build_scorecard(cells=["A"], facts=facts, execution_ref="")
        self.assertEqual(card["schema_version"], 1)
        self.assertEqual(card["status"], "baseline_only")
        self.assertIn("no_execution_ref", card["gaps"])
        self.assertGreaterEqual(card["completeness"], 0)

        card2 = build_scorecard(cells=["A"], facts=facts, execution_ref="XML-123")
        self.assertIn(card2["status"], ("awaiting_post", "ready"))

    def test_selection_roundtrip(self):
        from core.cases import selection

        empty = selection.get_selection("tester")
        self.assertEqual(empty["kind"], "empty")

        saved = selection.set_selection(
            "tester",
            {"kind": "cells", "cells": ["X", "Y"], "label": "cluster", "source": "map"},
        )
        self.assertEqual(saved["kind"], "cells")
        self.assertEqual(saved["cells"], ["X", "Y"])
        loaded = selection.get_selection("tester")
        self.assertEqual(loaded["cells"], ["X", "Y"])
        self.assertEqual(loaded["label"], "cluster")

    def test_open_case_from_issue_without_live_correlator_deps(self):
        from core.cases import service

        with mock.patch("core.cases.correlator._collect_cm_facts", return_value=[]), mock.patch(
            "core.cases.correlator._collect_pm_facts", return_value=[]
        ), mock.patch("core.cases.correlator._collect_alarm_facts", return_value=[]):
            case = service.open_case_from_issue(
                {
                    "id": "abc123",
                    "module": "Change Impact",
                    "category": "Configuration Impact",
                    "title": "Param changed",
                    "summary": "tilt 2→6",
                    "score": 65,
                    "severity": "Medium",
                    "cells": ["SITE1_A"],
                    "vendor": "Nokia",
                    "technology": "4G",
                    "source_url": "/change-impact",
                    "evidence": {"change": {"parameter": "tilt"}},
                },
                actor="malek",
            )
        self.assertEqual(case["source_module"], "Change Impact")
        self.assertEqual(case["source_issue_id"], "abc123")
        self.assertTrue(case["narrative"])
        self.assertIn("scorecard", case)
        self.assertEqual(case["scorecard"]["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
