"""One-off diagnostic for sector 5635_A AMLE extract."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import time
import traceback
from datetime import date

print("=== 5635_A AMLE diagnostic ===")

from modules.nokia_load_balancing.balance_data import sectors_from_balance
from modules.nokia_load_balancing.rules import (
    highest_lowest_layer,
    parse_sector_id,
    sector_id_from_row,
)

t0 = time.perf_counter()
sectors, errors, source = sectors_from_balance(["5635_A"], date.today())
print(f"Balance lookup: {time.perf_counter() - t0:.2f}s")
print("  source:", source)
print("  errors:", errors)
if sectors:
    s = sectors[0]
    print("  sector:", s.get("sector_id"), "throughput:", s.get("throughput"))
    hi, lo = highest_lowest_layer(s.get("throughput") or {})
    print("  highest_layer:", hi, "lowest_layer:", lo)

mrbts, letter = parse_sector_id("5635_A")
print(f"Parsed: mrbts={mrbts} letter={letter}")

from core.cm_extractor.site_catalog import resolve_nokia_netact_site_id, scope_dn_needles

netact = resolve_nokia_netact_site_id("5635")
needles = scope_dn_needles("5635", "MRBTS")
print(f"NetAct site id: {netact}")
print(f"DN needles ({len(needles)}):", list(needles)[:8])

from core.cm_extractor.config import nokia_configured, nokia_defaults

print("Nokia CM configured:", nokia_configured())
if nokia_configured():
    print("  host:", nokia_defaults().get("host"))

print("\n--- Scoped AMLEPR query ---")
rows = []
headers = []
try:
    from modules.nokia_load_balancing.logic import _build_amle_query_client, _query_amlepr_scoped

    client = _build_amle_query_client()
    print("  client timeout:", client.timeout, "max_retries:", client.max_retries)
    t1 = time.perf_counter()
    headers, rows, warnings = _query_amlepr_scoped(client, "5635")
    print(f"  query elapsed: {time.perf_counter() - t1:.2f}s")
    print("  warnings:", warnings)
    print("  headers:", headers)
    print("  row count:", len(rows))
    if rows:
        dn_idx = headers.index("DN") if "DN" in headers else 0
        print("  first DN:", rows[0][dn_idx])
        for i, row in enumerate(rows[:8]):
            d = {headers[j]: row[j] for j in range(min(len(headers), len(row)))}
            dn = str(d.get("DN", ""))[:90]
            sid = sector_id_from_row(d)
            print(
                f"  row{i}: sector_id={sid} MRBTS={d.get('MRBTS')} "
                f"LNCEL={d.get('LNCEL')} freq={d.get('targetCarrierFreq')} DN={dn}"
            )
except Exception as exc:
    print("  QUERY FAILED:", exc)
    traceback.print_exc()

print("\n--- Full analyze_sectors ---")
try:
    from modules.nokia_load_balancing.logic import analyze_sectors

    if not sectors:
        print("  SKIP: no balance data")
    else:
        t2 = time.perf_counter()
        result = analyze_sectors(sectors)
        elapsed = time.perf_counter() - t2
        print(f"  analyze elapsed: {elapsed:.2f}s")
        print("  success:", result.get("success"))
        print("  amle_row_count:", result.get("amle_row_count"))
        print("  change_count:", result.get("change_count"))
        print("  site_ids:", result.get("site_ids"))
        for w in (result.get("warnings") or [])[:20]:
            print("  warn:", w)
        for e in (result.get("errors") or [])[:5]:
            print("  err:", e)
        if result.get("rows"):
            print("  proposals:", len(result["rows"]))
            print("  first:", result["rows"][0].get("sector_id"), result["rows"][0].get("action"))
except Exception as exc:
    print("  ANALYZE FAILED:", exc)
    traceback.print_exc()

print("\n=== done ===")
