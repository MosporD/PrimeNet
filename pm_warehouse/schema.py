"""Warehouse schema: dimensions, ledger, and generated per-family fact tables.

Fact layout (the load-bearing decision, measured in the design doc):
one table per measurement family per grain, counters as columns, one row per
(object, binding, bucket). Zero/absent = NULL — a NULL costs one bit in the
heap null bitmap, which makes the measured 71 % zero-density nearly free.

Grains: h_ (hourly), d_ (daily), w_ (weekly), m_ (monthly). ROP grain is
deliberately absent from the pilot — the fold happens in memory on ingest.

Merge semantics differ by writer:
  ingest  → ACCUMULATE (ON CONFLICT adds sums, GREATEST/LEAST extremes)
  rollup  → REPLACE    (recomputes the whole target bucket from source grain,
                        so late-data re-rolls are idempotent)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .dictionary import column_name

_IDENT_RE = re.compile(r"[^a-z0-9_]+")

GRAINS = ("h", "d", "w", "m")


def family_table(family: str, grain: str) -> str:
    base = _IDENT_RE.sub("_", family.strip().lower()).strip("_") or "unknown"
    return f"{grain}_{base}"[:63]


@dataclass
class FamilyDef:
    family: str                       # measInfoId as observed on the wire
    counters: list[str]               # native ids, stable order
    rules: dict[str, str]             # native id -> SUM|AVG|MAX|MIN|CUM|LAST
    wide: set[str] = field(default_factory=set)   # native ids stored as double

    def columns(self) -> list[tuple[str, str, str]]:
        """(native_id, column, sql_type) per counter."""
        out = []
        for nid in self.counters:
            typ = "double precision" if nid in self.wide else "real"
            out.append((nid, column_name(nid), typ))
        return out


DDL_FIXED = """
CREATE SCHEMA IF NOT EXISTS pm;

CREATE TABLE IF NOT EXISTS pm.dim_object (
  object_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vendor      text NOT NULL,
  ne_class    text NOT NULL,
  base_dn     text NOT NULL,
  parent_id   bigint REFERENCES pm.dim_object(object_id),
  site_id     text,
  cell_name   text,
  technology  text,
  area        text,
  first_seen  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (vendor, base_dn)
);
CREATE INDEX IF NOT EXISTS ix_dim_object_parent ON pm.dim_object (parent_id);
CREATE INDEX IF NOT EXISTS ix_dim_object_class  ON pm.dim_object (ne_class);

CREATE TABLE IF NOT EXISTS pm.dim_binding (
  binding_id  int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  binding_key text NOT NULL UNIQUE
);
INSERT INTO pm.dim_binding (binding_id, binding_key)
  OVERRIDING SYSTEM VALUE VALUES (0, '')
  ON CONFLICT (binding_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS pm.dim_counter (
  counter_id  int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vendor      text NOT NULL,
  technology  text NOT NULL,
  native_id   text NOT NULL,
  family      text NOT NULL,
  column_name text NOT NULL,
  agg_rule    text NOT NULL,
  unit        text,
  display_name text,
  netact_name  text,
  dict_version text,
  UNIQUE (vendor, technology, native_id)
);
CREATE INDEX IF NOT EXISTS ix_dim_counter_family ON pm.dim_counter (family);

CREATE TABLE IF NOT EXISTS pm.dim_kpi (
  kpi_id      text PRIMARY KEY,
  vendor      text NOT NULL,
  technology  text NOT NULL,
  name        text NOT NULL,
  kpi_class   text,
  unit        text,
  formula     text NOT NULL,
  object_levels text,
  time_levels   text
);

CREATE TABLE IF NOT EXISTS pm.user_kpi (
  id          int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text NOT NULL UNIQUE,
  category    text,
  unit        text,
  description text,
  vendor      text NOT NULL DEFAULT 'nokia',
  technology  text NOT NULL DEFAULT '4G',
  formula     text NOT NULL,
  created_by  text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pm.ingest_ledger (
  file_key    text PRIMARY KEY,
  source_path text,
  vendor      text,
  ne_dn       text,
  rop_end_utc timestamptz,
  size_bytes  bigint,
  state       text NOT NULL DEFAULT 'claimed',
  rows_raw    bigint,
  rows_kept   bigint,
  parse_ms    int,
  write_ms    int,
  error       text,
  claimed_at  timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS pm.object_group (
  group_id    int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text NOT NULL UNIQUE,
  owner_id    int,
  ne_class    text NOT NULL,
  dim_policy  jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pm.object_group_member (
  group_id  int NOT NULL REFERENCES pm.object_group(group_id) ON DELETE CASCADE,
  object_id bigint NOT NULL REFERENCES pm.dim_object(object_id),
  PRIMARY KEY (group_id, object_id)
);
"""


def fact_table_ddl(fam: FamilyDef, grain: str) -> str:
    table = family_table(fam.family, grain)
    cols = ",\n  ".join(f'"{col}" {typ}' for _, col, typ in fam.columns())
    return f"""
CREATE TABLE IF NOT EXISTS pm.{table} (
  object_id  bigint NOT NULL,
  binding_id int NOT NULL DEFAULT 0,
  bucket     timestamptz NOT NULL,
  n_present  smallint NOT NULL,
  n_expected smallint NOT NULL,
  {cols},
  PRIMARY KEY (object_id, binding_id, bucket)
);
CREATE INDEX IF NOT EXISTS ix_{table}_bucket ON pm.{table} USING brin (bucket);
"""


def ensure_fact_columns_sql(fam: FamilyDef, grain: str) -> list[str]:
    """ALTER TABLE ADD COLUMN IF NOT EXISTS for schema evolution."""
    table = family_table(fam.family, grain)
    return [
        f'ALTER TABLE pm.{table} ADD COLUMN IF NOT EXISTS "{col}" {typ}'
        for _, col, typ in fam.columns()
    ]


def build_family_defs(
    observed: dict[str, list[str]],
    counter_dict: dict[str, dict],
) -> dict[str, FamilyDef]:
    """Merge wire-observed counters with dictionary metadata.

    ``observed``: family -> counters as seen in files (wire order preserved).
    Counters absent from the dictionary get rule SUM and a review-worthy
    default — never dropped (99.2 % coverage measured, so this is rare).
    """
    fams: dict[str, FamilyDef] = {}
    for family, counters in observed.items():
        seen: set[str] = set()
        ordered: list[str] = []
        for c in counters:
            if c not in seen:
                seen.add(c)
                ordered.append(c)
        rules = {}
        wide = set()
        for c in ordered:
            meta = counter_dict.get(c)
            rules[c] = meta["rule"] if meta else "SUM"
            if meta and meta.get("wide"):
                wide.add(c)
        fams[family] = FamilyDef(family=family, counters=ordered, rules=rules, wide=wide)
    return fams


def apply_schema(conn, fams: dict[str, FamilyDef]) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL_FIXED)
        for fam in fams.values():
            for grain in GRAINS:
                cur.execute(fact_table_ddl(fam, grain))
                for stmt in ensure_fact_columns_sql(fam, grain):
                    cur.execute(stmt)
    conn.commit()


def load_dictionary_rows(conn, counter_dict: dict[str, dict], kpis: list[dict],
                         fams: dict[str, FamilyDef],
                         vendor: str = "nokia", technology: str = "4G") -> None:
    fam_of: dict[str, str] = {}
    for fam in fams.values():
        for c in fam.counters:
            fam_of[c] = fam.family
    with conn.cursor() as cur:
        for nid, fam_name in fam_of.items():
            meta = counter_dict.get(nid) or {}
            cur.execute(
                """
                INSERT INTO pm.dim_counter
                  (vendor, technology, native_id, family, column_name, agg_rule,
                   unit, display_name, netact_name, dict_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (vendor, technology, native_id) DO UPDATE
                  SET family = EXCLUDED.family, agg_rule = EXCLUDED.agg_rule
                """,
                (vendor, technology, nid, fam_name, column_name(nid),
                 meta.get("rule", "SUM"), meta.get("unit"), meta.get("display"),
                 meta.get("netact"), meta.get("version")),
            )
        for k in kpis:
            if not k.get("kpi_id"):
                continue
            cur.execute(
                """
                INSERT INTO pm.dim_kpi
                  (kpi_id, vendor, technology, name, kpi_class, unit, formula,
                   object_levels, time_levels)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (kpi_id) DO UPDATE SET formula = EXCLUDED.formula
                """,
                (k["kpi_id"], vendor, technology, k["name"], k["kpi_class"],
                 k["unit"], k["formula"], k["object_levels"], k["time_levels"]),
            )
    conn.commit()
