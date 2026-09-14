"""Unit tests for PM Plus parser, ingest, KPI, rollup (SQLite)."""

from __future__ import annotations

import gzip
import os
import tempfile
import unittest
from pathlib import Path

# Isolate SQLite before importing pm_plus config consumers
_TMP = tempfile.mkdtemp(prefix="pm_plus_test_")
os.environ["PM_PLUS_SQLITE_PATH"] = str(Path(_TMP) / "test.db")
os.environ.pop("PM_PLUS_DATABASE_URL", None)
os.environ.pop("NCM_DATABASE_URL", None)

from core.pm_plus import config  # noqa: E402
from core.pm_plus.file_meta import parse_filename  # noqa: E402
from core.pm_plus.ingest import ingest_local_file  # noqa: E402
from core.pm_plus.kpi_compiler import eval_formula, validate_formula  # noqa: E402
from core.pm_plus.nokia_parser import CounterSample, fold_samples_to_hour, parse_file  # noqa: E402
from core.pm_plus.query import query_series, warehouse_stats  # noqa: E402
from core.pm_plus.rollup import rollup_hour_to_day  # noqa: E402
from core.pm_plus.schema import init_schema  # noqa: E402

SAMPLE = Path(__file__).resolve().parent / "testdata" / "sample_meas.xml"


class PmPlusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_schema()
        gz = Path(_TMP) / "sample.xml.gz"
        with open(SAMPLE, "rb") as src, gzip.open(gz, "wb") as dst:
            dst.write(src.read())
        cls.gz = gz
        cls.result = ingest_local_file(gz, host="test", stream="14", bucket="b1")

    def test_backend_sqlite(self):
        self.assertFalse(config.use_postgres())
        self.assertEqual(self.result["backend"], "sqlite")

    def test_parse_counts(self):
        parsed = parse_file(SAMPLE)
        self.assertEqual(len(parsed.samples), 6)
        self.assertIn("LTE_Cell_Avail", parsed.families)
        self.assertEqual(len(parsed.objects), 2)

    def test_ingest_timing(self):
        self.assertGreater(self.result["samples_15m"], 0)
        self.assertLess(self.result["total_seconds"], 5.0)

    def test_idempotent_reingest(self):
        before = warehouse_stats()["fact_hour"]
        ingest_local_file(self.gz, host="test", stream="14", bucket="b1")
        after = warehouse_stats()["fact_hour"]
        # ACCUMULATE doubles values but row count stays same
        self.assertEqual(before, after)

    def test_kpi_eval(self):
        self.assertEqual(eval_formula("M8005C1 / M8005C0 * 100", {"M8005C0": 900, "M8005C1": 890}), 890 / 900 * 100)
        self.assertIsNone(eval_formula("M8005C1 / M8005C0", {"M8005C0": 0, "M8005C1": 10}))
        v = validate_formula("M8005C1 / M8005C0 * 100")
        self.assertTrue(v["ok"])

    def test_query_formula(self):
        res = query_series(
            formula="M8005C1 / M8005C0 * 100",
            resolution="hour",
            limit=100,
        )
        self.assertTrue(res["summary"] or res["points"])

    def test_rollup_day(self):
        out = rollup_hour_to_day()
        self.assertGreaterEqual(out["daily_rows_upserted"], 1)
        self.assertGreaterEqual(warehouse_stats()["fact_day"], 1)

    def test_filename_meta(self):
        m = parse_filename("PM202609111231+030072MRBTS_-_1.xml.gz")
        self.assertEqual(m.ne_type, "MRBTS")
        self.assertEqual(m.shard, "1")
        m2 = parse_filename("PM202609111218+030072RNC.xml.gz")
        self.assertEqual(m2.ne_type, "RNC")
        self.assertEqual(m2.shard, "")

    def test_grain_not_mixed_in_hour_fold(self):
        samples = [
            CounterSample(
                bucket_ts="2026-09-11T12:05:00Z",
                object_dn="PLMN/MRBTS-1/NRCELL-1",
                family="NREIRP",
                counter_id="M1C1",
                value=10.0,
                gp_seconds=300,
                ne_type="MRBTS",
                stream="14",
            ),
            CounterSample(
                bucket_ts="2026-09-11T12:15:00Z",
                object_dn="PLMN/MRBTS-1/NRCELL-1",
                family="NRBF",
                counter_id="M1C1",
                value=20.0,
                gp_seconds=900,
                ne_type="MRBTS",
                stream="14",
            ),
        ]
        folded = fold_samples_to_hour(samples)
        self.assertEqual(len(folded), 2)
        gps = {k[3] for k in folded}
        self.assertEqual(gps, {300, 900})


if __name__ == "__main__":
    unittest.main()
