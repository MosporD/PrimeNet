"""Discover live RET naming vocabulary from Nokia RETU_R and Huawei RETSUBUNIT.

Pulls CM labels only — no technology mapping. Use the printed / JSON token tables
to build a truth table with the radio team, then wire mapping separately.

Examples:
  python scripts/_discover_ret_label_vocab.py
  python scripts/_discover_ret_label_vocab.py --huawei-limit 80 --nokia-sites 40
  python scripts/_discover_ret_label_vocab.py --out data/ret_label_vocab.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
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

from core.cm_extractor.extraction import build_huawei_client, build_nokia_client
from core.cm_extractor.nokia_client import NokiaCmError
from core.cm_extractor.nokia_semantics import (
    build_mo_path,
    query_parameters_individually,
    query_selected_parameters,
)
from modules.ret_management import logic as ret_logic

_SPLIT_RE = re.compile(r"[-_/]+")


def _as_text(value) -> str:
    text = str(value if value is not None else "").strip()
    if not text or text.lower() in ("none", "null", "nan", "?", "-"):
        return ""
    return text


def _tokens(label: str) -> list[str]:
    return [p for p in _SPLIT_RE.split(label) if p]


def _alias(row: dict, *names: str) -> str:
    for name in names:
        got = ret_logic._alias_lookup(row, name)
        if got:
            return _as_text(got)
    return ""


def discover_nokia(*, max_sites: int, conf_id: int = 1) -> dict:
    client = build_nokia_client()
    read_mo = ret_logic.resolve_nokia_retu_read_mo_class(client)
    adaptation, abbreviation = read_mo.split(":", 1)
    params = list(ret_logic.NOKIA_RETU_PARAMS)

    # Prefer one network-wide query (empty element scope). Fall back to sampling sites.
    mo_path = build_mo_path(adaptation, abbreviation, scope_level="MRBTS", element_id=None)
    headers: list[str] = []
    rows: list[list] = []
    mode = "network-wide"
    try:
        # Use a dummy site_id for API plumbing; NetAct often ignores it at PLMN scope.
        headers, rows = query_selected_parameters(
            client,
            mo_path,
            params,
            adaptation=adaptation,
            abbreviation=abbreviation,
            conf_id=conf_id,
            site_id="0",
            scope_level="MRBTS",
        )
    except NokiaCmError:
        headers, rows = [], []

    if not rows:
        mode = f"per-site-sample:{max_sites}"
        nes = ret_logic.list_network_elements("nokia", query="", limit=max_sites)
        seen_dn: set[str] = set()
        records_acc: list[dict] = []
        for ne in nes:
            site_id = str(ne.get("site_id") or "").strip()
            if not site_id:
                continue
            try:
                recs, _warn, _mo = ret_logic.fetch_nokia_retu_angles(
                    client, site_id=site_id, conf_id=conf_id
                )
            except Exception as exc:  # noqa: BLE001 — discovery continues
                print(f"  nokia site {site_id} skip: {exc}")
                continue
            for rec in recs:
                dn = _as_text(rec.get("runtime_DN") or rec.get("DN") or rec.get("dn"))
                if dn and dn in seen_dn:
                    continue
                if dn:
                    seen_dn.add(dn)
                records_acc.append(rec)
        records = records_acc
    else:
        records = ret_logic._rows_to_records(headers, rows)

    sector_ids = Counter()
    base_stations = Counter()
    ant_models = Counter()
    tokens = Counter()
    samples_by_token: dict[str, list[str]] = {}

    for rec in records:
        sid = _as_text(rec.get("sectorID"))
        if sid:
            sector_ids[sid] += 1
            for tok in _tokens(sid):
                tokens[tok] += 1
                samples_by_token.setdefault(tok, [])
                if sid not in samples_by_token[tok] and len(samples_by_token[tok]) < 5:
                    samples_by_token[tok].append(sid)
        bs = _as_text(rec.get("baseStationID"))
        if bs:
            base_stations[bs] += 1
        am = _as_text(rec.get("antModel"))
        if am:
            ant_models[am] += 1

    return {
        "vendor": "nokia",
        "mo": "RETU_R",
        "mo_class": read_mo,
        "query_mode": mode,
        "row_count": len(records),
        "distinct_sectorID": len(sector_ids),
        "sectorID_values": sector_ids.most_common(),
        "sectorID_tokens": tokens.most_common(),
        "token_examples": {
            tok: samples_by_token.get(tok, [])
            for tok, _n in tokens.most_common()
        },
        "baseStationID_sample": base_stations.most_common(30),
        "antModel_values": ant_models.most_common(),
        "fields_present": sorted({k for r in records for k in r.keys() if not str(k).startswith("_")}),
    }


def discover_huawei(*, max_nes: int) -> dict:
    client = build_huawei_client()
    client.login()
    nes = ret_logic.list_network_elements("huawei", query="", limit=max_nes)

    subunit_names = Counter()
    actual_sector_ids = Counter()
    tokens = Counter()
    samples_by_token: dict[str, list[str]] = {}
    field_presence = Counter()
    row_count = 0
    ne_ok = 0
    ne_fail = 0

    for ne in nes:
        ne_name = str(ne.get("ne_name") or ne.get("name") or "").strip()
        if not ne_name:
            continue
        try:
            # Bulk LST only — skip slow per-subunit enrichment for vocabulary scan.
            reports, errors = ret_logic._run_ret_mml(client, ne_name, "LST")
            rows = ret_logic._normalize_ret_rows(
                ret_logic._collect_ret_rows_from_reports(reports, ne_name=ne_name)
            )
            if errors and not rows:
                ne_fail += 1
                print(f"  huawei {ne_name[:50]} fail: {errors[0][:120]}")
                continue
            ne_ok += 1
        except Exception as exc:  # noqa: BLE001
            ne_fail += 1
            print(f"  huawei {ne_name[:50]} skip: {exc}")
            continue

        for row in rows:
            row_count += 1
            for key, value in row.items():
                if _as_text(value):
                    field_presence[str(key)] += 1
            name = _alias(row, "Subunit Name")
            if name:
                subunit_names[name] += 1
                for tok in _tokens(name):
                    tokens[tok] += 1
                    samples_by_token.setdefault(tok, [])
                    if name not in samples_by_token[tok] and len(samples_by_token[tok]) < 5:
                        samples_by_token[tok].append(name)
            actual = _alias(row, "Actual Sector ID")
            if actual:
                actual_sector_ids[actual] += 1

    return {
        "vendor": "huawei",
        "mo": "RETSUBUNIT",
        "query_mode": f"LST-per-NE:{max_nes}",
        "ne_ok": ne_ok,
        "ne_fail": ne_fail,
        "row_count": row_count,
        "distinct_Subunit_Name": len(subunit_names),
        "Subunit_Name_values": subunit_names.most_common(),
        "Subunit_Name_tokens": tokens.most_common(),
        "token_examples": {
            tok: samples_by_token.get(tok, [])
            for tok, _n in tokens.most_common()
        },
        "Actual_Sector_ID_values": actual_sector_ids.most_common(),
        "fields_with_values": field_presence.most_common(),
    }


def _print_section(title: str, pairs: list, *, limit: int = 80) -> None:
    print(f"\n=== {title} (top {min(limit, len(pairs))} of {len(pairs)}) ===")
    for value, count in pairs[:limit]:
        print(f"  {count:6d}  {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nokia-sites", type=int, default=60, help="Fallback sample size if network-wide Nokia query is empty")
    parser.add_argument("--huawei-limit", type=int, default=60, help="How many Huawei NEs to LST")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "ret_label_vocab.json")
    parser.add_argument("--skip-nokia", action="store_true")
    parser.add_argument("--skip-huawei", action="store_true")
    args = parser.parse_args()

    report: dict = {"nokia": None, "huawei": None}

    if not args.skip_nokia:
        print("Querying Nokia RETU_R …")
        report["nokia"] = discover_nokia(max_sites=args.nokia_sites)
        n = report["nokia"]
        print(
            f"Nokia: mode={n['query_mode']} rows={n['row_count']} "
            f"distinct sectorID={n['distinct_sectorID']}"
        )
        _print_section("Nokia sectorID full values", n["sectorID_values"], limit=100)
        _print_section("Nokia sectorID tokens (split on -_/)", n["sectorID_tokens"], limit=120)
        _print_section("Nokia antModel", n["antModel_values"], limit=40)

    if not args.skip_huawei:
        print("\nQuerying Huawei RETSUBUNIT (LST) …")
        report["huawei"] = discover_huawei(max_nes=args.huawei_limit)
        h = report["huawei"]
        print(
            f"Huawei: NEs ok={h['ne_ok']} fail={h['ne_fail']} rows={h['row_count']} "
            f"distinct Subunit Name={h['distinct_Subunit_Name']}"
        )
        _print_section("Huawei Subunit Name full values", h["Subunit_Name_values"], limit=100)
        _print_section("Huawei Subunit Name tokens (split on -_/)", h["Subunit_Name_tokens"], limit=120)
        _print_section("Huawei Actual Sector ID", h["Actual_Sector_ID_values"], limit=40)
        _print_section("Huawei fields with non-empty values", h["fields_with_values"], limit=40)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {args.out}")
    print(
        "\nNext: review token lists together and mark each token as "
        "sector / tech / band / polarity / other — then we code the truth table."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
