"""Import Nokia counter agg rules + KPI formulas from ref spreadsheet."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

from core.pm_plus.agg_rules import normalize_agg_rule
from core.pm_plus.db import connect, execute, fetchone, qident
from core.pm_plus.schema import init_schema


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _header_map(ws, max_scan: int = 15) -> tuple[int, dict[str, int]]:
    for i, row in enumerate(ws.iter_rows(max_row=max_scan, values_only=True)):
        vals = [str(c).strip() if c is not None else "" for c in row]
        if "Counter ID" in vals or "KPI ID" in vals:
            return i, {h: j for j, h in enumerate(vals) if h}
    raise ValueError("Header row not found")


def import_counter_agg_rules(xlsx: Path | str) -> dict:
    """Seed dim_counter time/nw agg + family defaults from Counter List."""
    init_schema()
    xlsx = Path(xlsx)
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb["Counter List"]
    header_i, idx = _header_map(ws)
    id_col = idx["Counter ID"]
    time_col = idx.get("Time aggregation function")
    nw_col = idx.get("NW aggregation function")
    meas_col = idx.get("Measurement Name")
    name_col = idx.get("NetAct Name") or idx.get("Network Element Name")

    family_votes: dict[str, dict[str, int]] = {}
    n_counters = 0
    now = _now()
    with connect() as conn:
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i <= header_i:
                continue
            cells = list(row)
            if id_col >= len(cells) or cells[id_col] is None:
                continue
            cid = str(cells[id_col]).strip()
            if not cid or cid == "Counter ID":
                continue
            # Prefer M-format IDs (NBI); also accept numeric
            time_agg = normalize_agg_rule(
                str(cells[time_col]).strip() if time_col is not None and time_col < len(cells) and cells[time_col] else "SUM"
            )
            nw_agg = normalize_agg_rule(
                str(cells[nw_col]).strip() if nw_col is not None and nw_col < len(cells) and cells[nw_col] else "SUM"
            )
            family = ""
            if meas_col is not None and meas_col < len(cells) and cells[meas_col]:
                family = str(cells[meas_col]).strip()
            # Measurement Abbreviated Name isn't on counter sheet — family from Measurement Name
            display = cid
            if name_col is not None and name_col < len(cells) and cells[name_col]:
                display = str(cells[name_col]).strip()

            execute(
                conn,
                f"INSERT INTO dim_counter "
                f"(counter_id, vendor, family, display_name, agg_rule, time_agg, nw_agg, "
                f"time_agg_override, nw_agg_override, updated_at) "
                f"VALUES (?,?,?,?,?,?,?,0,0,?) "
                f"ON CONFLICT(counter_id) DO UPDATE SET "
                f"family=COALESCE(NULLIF(excluded.family,''), dim_counter.family), "
                f"display_name=COALESCE(NULLIF(excluded.display_name,''), dim_counter.display_name), "
                f"time_agg=CASE WHEN dim_counter.time_agg_override=1 THEN dim_counter.time_agg ELSE excluded.time_agg END, "
                f"nw_agg=CASE WHEN dim_counter.nw_agg_override=1 THEN dim_counter.nw_agg ELSE excluded.nw_agg END, "
                f"agg_rule=CASE WHEN dim_counter.time_agg_override=1 THEN dim_counter.agg_rule ELSE excluded.time_agg END, "
                f"updated_at=excluded.updated_at",
                (cid, "nokia", family, display, time_agg, time_agg, nw_agg, now),
            )
            n_counters += 1
            if family:
                votes = family_votes.setdefault(family, {})
                votes[time_agg] = votes.get(time_agg, 0) + 1

        # Family default = majority time_agg among its counters; nw same majority of nw later
        for fam, votes in family_votes.items():
            majority = max(votes.items(), key=lambda x: x[1])[0]
            execute(
                conn,
                "INSERT INTO agg_rule_family (family, ne_type, time_agg, nw_agg, enabled, updated_at) "
                "VALUES (?,?,?,?,1,?) "
                "ON CONFLICT(family, ne_type) DO UPDATE SET "
                "time_agg=excluded.time_agg, updated_at=excluded.updated_at",
                (fam, "", majority, majority, now),
            )
        conn.commit()
    wb.close()
    return {"counters_upserted": n_counters, "families": len(family_votes)}


def import_kpi_formulas(xlsx: Path | str, *, created_by: str = "catalog") -> dict:
    """Import KPI List formulas into kpi_definitions."""
    init_schema()
    xlsx = Path(xlsx)
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb["KPI List"]
    header_i, idx = _header_map(ws)
    now = _now()
    n = 0
    skipped = 0
    with connect() as conn:
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i <= header_i:
                continue
            cells = list(row)

            def cell(name: str) -> str:
                j = idx.get(name)
                if j is None or j >= len(cells) or cells[j] is None:
                    return ""
                return str(cells[j]).strip()

            kpi_id = cell("KPI ID")
            name = cell("KPI Name") or kpi_id
            formula = cell("KPI Formula (with Counter IDs)")
            if not formula or not name:
                skipped += 1
                continue
            existing = fetchone(
                conn,
                "SELECT id FROM kpi_definitions WHERE name=? OR kpi_id=?",
                (name, kpi_id or name),
            )
            payload = (
                name,
                formula,
                cell("Description"),
                "nokia",
                "cell",
                kpi_id,
                cell("KPI Abbreviation"),
                cell("Technology"),
                cell("Unit"),
                cell("Measurement"),
                cell("Object Summary Levels"),
                cell("Time Summary Levels"),
                "nokia_catalog",
                1,
                created_by,
                now,
                now,
            )
            if existing:
                execute(
                    conn,
                    "UPDATE kpi_definitions SET formula=?, description=?, kpi_id=?, abbreviation=?, "
                    "technology=?, unit=?, measurement=?, object_levels=?, time_levels=?, "
                    "source='nokia_catalog', updated_at=? WHERE id=?",
                    (
                        formula,
                        cell("Description"),
                        kpi_id,
                        cell("KPI Abbreviation"),
                        cell("Technology"),
                        cell("Unit"),
                        cell("Measurement"),
                        cell("Object Summary Levels"),
                        cell("Time Summary Levels"),
                        now,
                        existing["id"],
                    ),
                )
            else:
                execute(
                    conn,
                    "INSERT INTO kpi_definitions "
                    "(name, formula, description, vendor, scope_default, kpi_id, abbreviation, "
                    "technology, unit, measurement, object_levels, time_levels, source, enabled, "
                    "created_by, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    payload,
                )
            n += 1
        conn.commit()
    wb.close()
    return {"kpis_upserted": n, "skipped": skipped}


def import_nokia_catalog(xlsx: Path | str) -> dict:
    agg = import_counter_agg_rules(xlsx)
    kpis = import_kpi_formulas(xlsx)
    return {**agg, **kpis}
