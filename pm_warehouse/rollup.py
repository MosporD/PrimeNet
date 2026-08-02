"""Set-based rollups: h → d → w → m, entirely inside Postgres.

REPLACE semantics: each run recomputes whole target buckets from the source
grain (never merges increments), so re-rolling after late data is idempotent —
run it as often as you like, the result is always "as if computed once from
the full source". This is the safe counterpart to the ingest writer's
ACCUMULATE semantics.

Aggregation per counter column follows its agg_rule:
  SUM/AVG/CUM → SUM(col)   (AVG divides by n_present at read time)
  MAX → MAX(col), MIN → MIN(col), LAST → last non-null by bucket order
"""

from __future__ import annotations

from .schema import FamilyDef, family_table

# target grain -> (source grain, date_trunc unit, n_expected SQL at 900s ROP)
ROLLUPS = {
    "d": ("h", "day", "96"),
    "w": ("d", "week", "672"),
    "m": ("d", "month",
          "(96 * extract(day from (date_trunc('month', bucket) "
          "+ interval '1 month' - interval '1 day'))::int)"),
}


def _agg_expr(rule: str, col: str) -> str:
    q = f'"{col}"'
    if rule in ("SUM", "AVG", "CUM"):
        return f"SUM({q})"
    if rule == "MAX":
        return f"MAX({q})"
    if rule == "MIN":
        return f"MIN({q})"
    # LAST: value at the latest source bucket that has one
    return f"(ARRAY_REMOVE(ARRAY_AGG({q} ORDER BY bucket), NULL))[1]"


def rollup_sql(fam: FamilyDef, target: str) -> str:
    source, unit, n_expected = ROLLUPS[target]
    src = family_table(fam.family, source)
    dst = family_table(fam.family, target)
    cols = [(col, fam.rules[nid]) for nid, col, _ in fam.columns()]
    col_list = ", ".join(f'"{c}"' for c, _ in cols)
    agg_list = ", ".join(_agg_expr(r, c) for c, r in cols)
    set_list = ", ".join(
        ['n_present = EXCLUDED.n_present']
        + [f'"{c}" = EXCLUDED."{c}"' for c, _ in cols]
    )
    return f"""
INSERT INTO pm.{dst} AS t
  (object_id, binding_id, bucket, n_present, n_expected, {col_list})
SELECT object_id, binding_id,
       date_trunc('{unit}', bucket) AS bucket,
       SUM(n_present)::smallint,
       ({n_expected})::smallint,
       {agg_list}
FROM pm.{src}
WHERE bucket >= %(t0)s AND bucket < %(t1)s
GROUP BY object_id, binding_id, date_trunc('{unit}', bucket)
ON CONFLICT (object_id, binding_id, bucket) DO UPDATE SET {set_list}
"""


def run_rollups(conn, fams: dict[str, FamilyDef], t0, t1,
                targets: tuple[str, ...] = ("d", "w", "m")) -> dict[str, int]:
    """Roll [t0, t1) through each target grain. Returns rows written per grain."""
    written: dict[str, int] = {}
    with conn.cursor() as cur:
        for target in targets:
            n = 0
            for fam in fams.values():
                cur.execute(rollup_sql(fam, target), {"t0": t0, "t1": t1})
                n += cur.rowcount
            written[target] = n
    conn.commit()
    return written
