"""Unit tests for core.cases (no live PM/CM required)."""

from __future__ import annotations

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

        card = build_scorecard(cells=["A"], facts=facts, execution_ref="", pull_pm=False)
        self.assertEqual(card["schema_version"], 2)
        self.assertEqual(card["status"], "baseline_only")
        self.assertIn("no_execution_ref", card["gaps"])
        self.assertGreaterEqual(card["completeness"], 0)

        with mock.patch("core.cases.scorecard._pull_pm_signals", return_value=[]):
            card2 = build_scorecard(cells=["A"], facts=facts, execution_ref="XML-123", pull_pm=True)
        self.assertIn(card2["status"], ("awaiting_post", "ready"))

        post_signals = [
            {"cell": "A", "category": "Accessibility", "change_pct": -2},
        ]
        with mock.patch("core.cases.scorecard._pull_pm_signals", return_value=post_signals):
            card3 = build_scorecard(cells=["A"], facts=facts, execution_ref="XML-123", pull_pm=True)
        self.assertEqual(card3["status"], "ready")
        self.assertIn(card3["verdict"], ("improve", "worsen", "flat", "inconclusive"))
        self.assertEqual(card3["post"]["signal_count"], 1)

    def test_identity_normalize(self):
        from core.cases import identity

        self.assertTrue(identity.cells_match("SITE1_A", "site1-a"))
        self.assertTrue(identity.cells_match("ABC/1", "abc_1"))
        rows = [{"cell_name": "SITE1_A"}, {"cell_name": "OTHER"}]
        matched = identity.filter_rows_for_cells(rows, ["site1-a"])
        self.assertEqual(len(matched), 1)

    def test_morning_report_dedupe(self):
        from core.cases import service, store

        with mock.patch("core.cases.correlator._collect_cm_facts", return_value=[]), mock.patch(
            "core.cases.correlator._collect_pm_facts", return_value=[]
        ), mock.patch("core.cases.correlator._collect_alarm_facts", return_value=[]), mock.patch(
            "core.cases.correlator._collect_neighbor_facts", return_value=[]
        ), mock.patch(
            "core.cases.correlator._collect_overshoot_facts", return_value=[]
        ):
            first = service.open_cases_from_morning_report(
                [
                    {
                        "id": "mr-1",
                        "title": "Crit outage",
                        "severity": "Critical",
                        "score": 90,
                        "cells": ["C1"],
                        "module": "Radio Morning Report",
                    }
                ],
                actor="malek",
            )
            self.assertEqual(first["created_count"], 1)
            second = service.open_cases_from_morning_report(
                [
                    {
                        "id": "mr-1",
                        "title": "Crit outage again",
                        "severity": "Critical",
                        "score": 90,
                        "cells": ["C1"],
                    }
                ],
                actor="malek",
            )
            self.assertEqual(second["created_count"], 0)
            self.assertEqual(second["skipped"][0]["reason"], "deduped")
            self.assertTrue(store.find_by_source_issue("mr-1"))

    def test_related_by_cells(self):
        from core.cases import store

        a = store.create_case({"title": "One", "cells": ["CELL_X"], "severity": "High"}, actor="a")
        b = store.create_case({"title": "Two", "cells": ["cell-x", "OTHER"], "severity": "Medium"}, actor="b")
        related = store.find_related_by_cells(["CELL_X"], exclude_case_id=a["case_id"], within_days=30)
        ids = {r["case_id"] for r in related}
        self.assertIn(b["case_id"], ids)
        self.assertNotIn(a["case_id"], ids)

    def test_conflict_guard(self):
        from core.cases import store
        from core.cases.gates import assert_can_approve, find_conflicts

        c1 = store.create_case(
            {
                "title": "Tilt change",
                "cells": ["CELL_Z"],
                "proposed_change": "increase electrical tilt to 6",
            },
            actor="a",
        )
        # Force proposed via transitions
        store.transition_case(c1["case_id"], "assigned", actor="a")
        store.transition_case(c1["case_id"], "proposed", actor="a")

        c2 = store.create_case(
            {
                "title": "Tilt again",
                "cells": ["cell_z"],
                "proposed_change": "increase electrical tilt to 8",
            },
            actor="b",
        )
        store.transition_case(c2["case_id"], "assigned", actor="b")
        store.transition_case(c2["case_id"], "proposed", actor="b")

        conflicts = find_conflicts(store.get_case(c2["case_id"]))
        self.assertTrue(any(c.get("shared_tokens") for c in conflicts))
        with self.assertRaises(store.CaseError):
            assert_can_approve(store.get_case(c2["case_id"]))
        # Override allowed
        assert_can_approve(store.get_case(c2["case_id"]), override_note="reviewed with peer")

    def test_impact_and_treatments(self):
        from core.cases import impact, treatments

        pack = impact.compute_impact_score(severity="Critical", score=80, cells=["A", "B"])
        self.assertEqual(pack["label"], "Impact Score (PM)")
        self.assertGreater(pack["impact_score"], 0)

        treatments.record_outcome(title="Downtilt fix", category="Overshoot", verdict="improve")
        treatments.record_outcome(title="Downtilt fix", category="Overshoot", verdict="improve")
        treatments.record_outcome(title="Downtilt fix", category="Overshoot", verdict="improve")
        trusted = treatments.list_trusted(min_improve=3)
        self.assertTrue(any(t["title"] == "Downtilt fix" for t in trusted))

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
        ), mock.patch("core.cases.correlator._collect_alarm_facts", return_value=[]), mock.patch(
            "core.cases.correlator._collect_neighbor_facts", return_value=[]
        ), mock.patch(
            "core.cases.correlator._collect_overshoot_facts", return_value=[]
        ):
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
        self.assertEqual(case["scorecard"]["schema_version"], 2)
        self.assertGreaterEqual(case.get("impact_score") or 0, 0)

    def test_nl_filters_no_sql(self):
        from core.pm_plus.nl_filters import compile_nl_to_filters

        out = compile_nl_to_filters("Nokia 4G site ABC availability")
        self.assertFalse(out["executed_sql"])
        types = {c["type"] for c in out["chips"]}
        self.assertIn("vendor", types)
        self.assertIn("technology", types)
        self.assertIn("site", types)


if __name__ == "__main__":
    unittest.main()
