"""Ingest: stream-parse → in-memory fold to hourly → COPY + monoid merge.

The fold is the efficiency core. Raw values never become database rows: blocks
fold in memory to (object, binding, family, hour) rows, and only those touch
Postgres. Measured in the design: 28.4 G raw values/day network-wide collapse
to ~223 M hourly rows/day.

Merge rules (ACCUMULATE semantics, per counter's agg_rule):
  SUM/CUM : NULL-preserving addition
  AVG     : addition (column holds the running sum; n_present divides at read)
  MAX/MIN : GREATEST / LEAST (Postgres ignores NULL operands)
  LAST    : overwrite
Idempotency comes from the ledger, not the merge — re-adding the same file
would double SUM counters, so a file is folded exactly once per claim.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from datetime import datetime

from .nokia_adapter import AdapterError, Block, iter_blocks
from .schema import FamilyDef, family_table

HOUR = 3600


def file_key(vendor: str, ne_dn: str, rop_end_utc: str, size: int) -> str:
    h = hashlib.sha256(f"{vendor}|{ne_dn}|{rop_end_utc}|{size}".encode())
    return h.hexdigest()


def floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


class HourFold:
    """(family, base_dn, binding, hour) -> per-counter monoid state.

    State per counter is a single float slot merged by rule, plus one shared
    n_present per row (all counters in a block share presence — measResults
    always carries the full counter list of its measTypes).
    """

    def __init__(self, fams: dict[str, FamilyDef]):
        self.fams = fams
        # rows[family][(base_dn, binding, hour)] = [n_present, {idx: value}]
        self.rows: dict[str, dict[tuple, list]] = defaultdict(dict)
        self.idx: dict[str, dict[str, int]] = {
            f: {c: i for i, c in enumerate(fd.counters)} for f, fd in fams.items()
        }
        self.raw_values = 0
        self.kept_values = 0

    def add(self, b: Block) -> None:
        fam = self.fams.get(b.family)
        if fam is None:
            return  # family not in schema; caller decides whether to extend
        idx = self.idx[b.family]
        key = (b.base_dn, b.binding_key, floor_hour(b.bucket_utc))
        row = self.rows[b.family].get(key)
        if row is None:
            row = [0, {}]
            self.rows[b.family][key] = row
        row[0] += 1
        acc: dict[int, float] = row[1]
        rules = fam.rules
        self.raw_values += len(b.values)
        for nid, val in zip(b.counters, b.values):
            if val is None:
                continue
            i = idx.get(nid)
            if i is None:
                continue
            self.kept_values += 1
            rule = rules[nid]
            cur = acc.get(i)
            if cur is None:
                acc[i] = val
            elif rule in ("SUM", "AVG", "CUM"):
                acc[i] = cur + val
            elif rule == "MAX":
                acc[i] = val if val > cur else cur
            elif rule == "MIN":
                acc[i] = val if val < cur else cur
            else:  # LAST
                acc[i] = val


def _merge_set_clause(fam: FamilyDef) -> str:
    parts = ["n_present = t.n_present + EXCLUDED.n_present"]
    for nid, col, _typ in fam.columns():
        rule = fam.rules[nid]
        e, c = f'EXCLUDED."{col}"', f't."{col}"'
        if rule in ("SUM", "AVG", "CUM"):
            parts.append(
                f'"{col}" = CASE WHEN {c} IS NULL AND {e} IS NULL THEN NULL '
                f"ELSE COALESCE({c},0) + COALESCE({e},0) END"
            )
        elif rule == "MAX":
            parts.append(f'"{col}" = GREATEST({c}, {e})')
        elif rule == "MIN":
            parts.append(f'"{col}" = LEAST({c}, {e})')
        else:  # LAST
            parts.append(f'"{col}" = COALESCE({e}, {c})')
    return ", ".join(parts)


class HourWriter:
    """COPY each family's folded rows into a temp stage, then one merge INSERT."""

    def __init__(self, conn, fams: dict[str, FamilyDef]):
        self.conn = conn
        self.fams = fams
        self._object_cache: dict[str, int] = {}
        self._binding_cache: dict[str, int] = {"": 0}

    # ---- dimension interning -------------------------------------------
    def object_id(self, base_dn: str, vendor: str = "nokia") -> int:
        oid = self._object_cache.get(base_dn)
        if oid is not None:
            return oid
        ne_class = base_dn.split("/")[-1].split("-")[0] or "UNKNOWN"
        parent_dn = "/".join(base_dn.split("/")[:-1])
        parent_id = self.object_id(parent_dn, vendor) if "/" in base_dn else None
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pm.dim_object (vendor, ne_class, base_dn, parent_id)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (vendor, base_dn)
                  DO UPDATE SET last_seen = now()
                RETURNING object_id
                """,
                (vendor, ne_class, base_dn, parent_id),
            )
            oid = cur.fetchone()[0]
        self._object_cache[base_dn] = oid
        return oid

    def binding_id(self, key: str) -> int:
        bid = self._binding_cache.get(key)
        if bid is not None:
            return bid
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pm.dim_binding (binding_key) VALUES (%s)
                ON CONFLICT (binding_key) DO UPDATE SET binding_key = EXCLUDED.binding_key
                RETURNING binding_id
                """,
                (key,),
            )
            bid = cur.fetchone()[0]
        self._binding_cache[key] = bid
        return bid

    # ---- fact write -----------------------------------------------------
    def write(self, fold: HourFold, rops_per_hour: int = 4) -> int:
        # Intern every dimension BEFORE any COPY begins: psycopg forbids other
        # statements on a connection while a COPY is active, and dim interning
        # issues INSERT..RETURNING.
        for rows in fold.rows.values():
            for base_dn, binding, _hour in rows:
                self.object_id(base_dn)
                self.binding_id(binding)

        total = 0
        with self.conn.cursor() as cur:
            for family, rows in fold.rows.items():
                if not rows:
                    continue
                fam = self.fams[family]
                table = family_table(family, "h")
                cols = [col for _, col, _ in fam.columns()]
                col_list = ", ".join(f'"{c}"' for c in cols)
                cur.execute(
                    f"CREATE TEMP TABLE stage (LIKE pm.{table} INCLUDING DEFAULTS)"
                )
                with cur.copy(
                    f'COPY stage (object_id, binding_id, bucket, n_present, '
                    f"n_expected, {col_list}) FROM STDIN"
                ) as copy:
                    for (base_dn, binding, hour), (n_present, acc) in rows.items():
                        record = [
                            self._object_cache[base_dn],
                            self._binding_cache[binding],
                            hour,
                            n_present,
                            rops_per_hour,
                        ] + [acc.get(i) for i in range(len(cols))]
                        copy.write_row(record)
                        total += 1
                cur.execute(
                    f"INSERT INTO pm.{table} AS t "
                    f"(object_id, binding_id, bucket, n_present, n_expected, {col_list}) "
                    f"SELECT object_id, binding_id, bucket, n_present, n_expected, "
                    f"{col_list} FROM stage "
                    f"ON CONFLICT (object_id, binding_id, bucket) DO UPDATE SET "
                    + _merge_set_clause(fam)
                )
                cur.execute("DROP TABLE stage")
        self.conn.commit()
        return total


# ---- ledger -------------------------------------------------------------

def claim(conn, key: str, *, source_path: str, vendor: str, ne_dn: str,
          rop_end_utc, size_bytes: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pm.ingest_ledger
              (file_key, source_path, vendor, ne_dn, rop_end_utc, size_bytes)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (file_key) DO NOTHING
            RETURNING file_key
            """,
            (key, source_path, vendor, ne_dn, rop_end_utc, size_bytes),
        )
        got = cur.fetchone() is not None
    conn.commit()
    return got


def complete(conn, key: str, *, rows_raw: int, rows_kept: int,
             parse_ms: int, write_ms: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pm.ingest_ledger
               SET state='done', rows_raw=%s, rows_kept=%s, parse_ms=%s,
                   write_ms=%s, completed_at=now()
             WHERE file_key=%s
            """,
            (rows_raw, rows_kept, parse_ms, write_ms, key),
        )
    conn.commit()


def fail(conn, key: str, error: str, state: str = "failed") -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE pm.ingest_ledger SET state=%s, error=%s, completed_at=now() "
            "WHERE file_key=%s",
            (state, error[:2000], key),
        )
    conn.commit()


# ---- per-file driver -----------------------------------------------------

def ingest_file(conn, path: str, fams: dict[str, FamilyDef],
                sum_rule: set[str], vendor: str = "nokia") -> dict:
    """Claim → parse+fold → write → complete. Returns timing/row stats."""
    size = os.path.getsize(path)
    # cheap identity probe: NE + ROP end from the filename when present,
    # else content hash of the head
    base = os.path.basename(path)
    key = file_key(vendor, base, "", size)

    if not claim(conn, key, source_path=path, vendor=vendor, ne_dn=base,
                 rop_end_utc=None, size_bytes=size):
        return {"skipped": True, "key": key}

    fold = HourFold(fams)
    t0 = time.perf_counter()
    try:
        for block in iter_blocks(path, sum_rule=sum_rule):
            fold.add(block)
    except AdapterError as exc:
        fail(conn, key, str(exc), state="quarantined")
        return {"quarantined": True, "key": key, "error": str(exc)}
    except Exception as exc:
        fail(conn, key, repr(exc))
        raise
    parse_ms = int((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()
    writer = HourWriter(conn, fams)
    rows = writer.write(fold)
    write_ms = int((time.perf_counter() - t1) * 1000)

    complete(conn, key, rows_raw=fold.raw_values, rows_kept=fold.kept_values,
             parse_ms=parse_ms, write_ms=write_ms)
    return {
        "key": key, "rows": rows, "raw_values": fold.raw_values,
        "kept_values": fold.kept_values, "parse_ms": parse_ms,
        "write_ms": write_ms,
    }
