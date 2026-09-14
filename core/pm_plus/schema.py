"""Schema bootstrap for Performance Explorer Plus.

Grain model (do not collapse these in primary keys):
- bucket_ts     : ROP end time (or hour/day floor for rollups)
- gp_seconds    : native granPeriod (300 / 900 / 1800 / …) — never mix
- ne_type       : file NE class (MRBTS / LNBTS / WBTS / RNC / BSC / NETACT)
- stream        : NBI stream id (14 / 15 / …)
- object_dn     : measured MO
- counter_id    : Nokia counter
- family        : measInfoId (dimension, not always in PK)
"""

from __future__ import annotations

from core.pm_plus import config
from core.pm_plus.db import connect, execute, fetchone, qident

SCHEMA_VERSION = 3


DDL_SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    host TEXT NOT NULL,
    stream TEXT NOT NULL,
    bucket TEXT NOT NULL,
    relpath TEXT NOT NULL,
    size_bytes INTEGER,
    mtime_epoch REAL,
    content_hash TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    error_message TEXT,
    local_path TEXT,
    rows_written INTEGER DEFAULT 0,
    ne_type TEXT,
    shard TEXT,
    file_begin TEXT,
    file_end TEXT,
    gp_seconds_set TEXT,
    discovered_at TEXT,
    claimed_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE(vendor, host, stream, bucket, relpath)
);

CREATE TABLE IF NOT EXISTS dim_object (
    object_dn TEXT PRIMARY KEY,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    tech TEXT,
    ne_type TEXT,
    mo_class TEXT,
    site_key TEXT,
    controller_key TEXT,
    base_dn TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS dim_counter (
    counter_id TEXT PRIMARY KEY,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    family TEXT,
    display_name TEXT,
    agg_rule TEXT NOT NULL DEFAULT 'SUM',
    time_agg TEXT NOT NULL DEFAULT 'SUM',
    nw_agg TEXT NOT NULL DEFAULT 'SUM',
    time_agg_override INTEGER NOT NULL DEFAULT 0,
    nw_agg_override INTEGER NOT NULL DEFAULT 0,
    unit TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS dim_family (
    family TEXT NOT NULL,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    ne_type TEXT NOT NULL DEFAULT '',
    default_gp_seconds INTEGER,
    updated_at TEXT,
    PRIMARY KEY (family, vendor, ne_type)
);

CREATE TABLE IF NOT EXISTS agg_rule_family (
    family TEXT NOT NULL,
    ne_type TEXT NOT NULL DEFAULT '',
    time_agg TEXT NOT NULL DEFAULT 'SUM',
    nw_agg TEXT NOT NULL DEFAULT 'SUM',
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT,
    PRIMARY KEY (family, ne_type)
);

CREATE TABLE IF NOT EXISTS fact_values_15m (
    bucket_ts TEXT NOT NULL,
    object_dn TEXT NOT NULL,
    counter_id TEXT NOT NULL,
    gp_seconds INTEGER NOT NULL DEFAULT 900,
    ne_type TEXT NOT NULL DEFAULT '',
    stream TEXT NOT NULL DEFAULT '',
    family TEXT,
    value REAL,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    sample_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
);

CREATE TABLE IF NOT EXISTS fact_values_hour (
    bucket_ts TEXT NOT NULL,
    object_dn TEXT NOT NULL,
    counter_id TEXT NOT NULL,
    gp_seconds INTEGER NOT NULL DEFAULT 900,
    ne_type TEXT NOT NULL DEFAULT '',
    stream TEXT NOT NULL DEFAULT '',
    family TEXT,
    value REAL,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    sample_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
);

CREATE TABLE IF NOT EXISTS fact_values_day (
    bucket_ts TEXT NOT NULL,
    object_dn TEXT NOT NULL,
    counter_id TEXT NOT NULL,
    gp_seconds INTEGER NOT NULL DEFAULT 900,
    ne_type TEXT NOT NULL DEFAULT '',
    stream TEXT NOT NULL DEFAULT '',
    family TEXT,
    value REAL,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    sample_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
);

CREATE TABLE IF NOT EXISTS fact_values_week (
    bucket_ts TEXT NOT NULL,
    object_dn TEXT NOT NULL,
    counter_id TEXT NOT NULL,
    gp_seconds INTEGER NOT NULL DEFAULT 900,
    ne_type TEXT NOT NULL DEFAULT '',
    stream TEXT NOT NULL DEFAULT '',
    family TEXT,
    value REAL,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    sample_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
);

CREATE TABLE IF NOT EXISTS fact_values_month (
    bucket_ts TEXT NOT NULL,
    object_dn TEXT NOT NULL,
    counter_id TEXT NOT NULL,
    gp_seconds INTEGER NOT NULL DEFAULT 900,
    ne_type TEXT NOT NULL DEFAULT '',
    stream TEXT NOT NULL DEFAULT '',
    family TEXT,
    value REAL,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    sample_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
);

CREATE TABLE IF NOT EXISTS fact_values_year (
    bucket_ts TEXT NOT NULL,
    object_dn TEXT NOT NULL,
    counter_id TEXT NOT NULL,
    gp_seconds INTEGER NOT NULL DEFAULT 900,
    ne_type TEXT NOT NULL DEFAULT '',
    stream TEXT NOT NULL DEFAULT '',
    family TEXT,
    value REAL,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    sample_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
);

CREATE TABLE IF NOT EXISTS kpi_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    formula TEXT NOT NULL,
    description TEXT,
    vendor TEXT NOT NULL DEFAULT 'nokia',
    scope_default TEXT DEFAULT 'cell',
    kpi_id TEXT,
    abbreviation TEXT,
    technology TEXT,
    unit TEXT,
    measurement TEXT,
    object_levels TEXT,
    time_levels TEXT,
    source TEXT DEFAULT 'manual',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS saved_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS ingest_lag_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    lag_minutes REAL,
    backlog_files INTEGER,
    failed_files INTEGER,
    last_rop TEXT,
    detail_json TEXT
);
"""

DDL_SQLITE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_ledger_status ON ingest_ledger(status);
CREATE INDEX IF NOT EXISTS idx_ledger_bucket ON ingest_ledger(stream, bucket);
CREATE INDEX IF NOT EXISTS idx_ledger_ne ON ingest_ledger(ne_type);
CREATE INDEX IF NOT EXISTS idx_fact15_obj_ts ON fact_values_15m(object_dn, bucket_ts);
CREATE INDEX IF NOT EXISTS idx_fact15_grain ON fact_values_15m(gp_seconds, ne_type, stream);
CREATE INDEX IF NOT EXISTS idx_fact_h_obj_ts ON fact_values_hour(object_dn, bucket_ts);
CREATE INDEX IF NOT EXISTS idx_fact_h_grain ON fact_values_hour(gp_seconds, ne_type, stream);
CREATE INDEX IF NOT EXISTS idx_fact_d_obj_ts ON fact_values_day(object_dn, bucket_ts);
CREATE INDEX IF NOT EXISTS idx_fact_w_obj_ts ON fact_values_week(object_dn, bucket_ts);
CREATE INDEX IF NOT EXISTS idx_fact_m_obj_ts ON fact_values_month(object_dn, bucket_ts);
CREATE INDEX IF NOT EXISTS idx_fact_y_obj_ts ON fact_values_year(object_dn, bucket_ts);
CREATE INDEX IF NOT EXISTS idx_fact_h_counter ON fact_values_hour(counter_id, bucket_ts);
CREATE INDEX IF NOT EXISTS idx_dim_obj_site ON dim_object(site_key);
CREATE INDEX IF NOT EXISTS idx_dim_obj_ne ON dim_object(ne_type, mo_class);
CREATE INDEX IF NOT EXISTS idx_dim_family ON dim_family(family);
CREATE INDEX IF NOT EXISTS idx_agg_family ON agg_rule_family(family);
CREATE INDEX IF NOT EXISTS idx_kpi_id ON kpi_definitions(kpi_id);
"""

# Full script for fresh DBs / tests
DDL_SQLITE = DDL_SQLITE_TABLES + DDL_SQLITE_INDEXES

DDL_PG_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS {q}schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}ingest_ledger (
        id BIGSERIAL PRIMARY KEY,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        host TEXT NOT NULL,
        stream TEXT NOT NULL,
        bucket TEXT NOT NULL,
        relpath TEXT NOT NULL,
        size_bytes BIGINT,
        mtime_epoch DOUBLE PRECISION,
        content_hash TEXT,
        status TEXT NOT NULL DEFAULT 'discovered',
        error_message TEXT,
        local_path TEXT,
        rows_written INTEGER DEFAULT 0,
        ne_type TEXT,
        shard TEXT,
        file_begin TEXT,
        file_end TEXT,
        gp_seconds_set TEXT,
        discovered_at TIMESTAMPTZ,
        claimed_at TIMESTAMPTZ,
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        UNIQUE(vendor, host, stream, bucket, relpath)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}dim_object (
        object_dn TEXT PRIMARY KEY,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        tech TEXT,
        ne_type TEXT,
        mo_class TEXT,
        site_key TEXT,
        controller_key TEXT,
        base_dn TEXT,
        updated_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}dim_counter (
        counter_id TEXT PRIMARY KEY,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        family TEXT,
        display_name TEXT,
        agg_rule TEXT NOT NULL DEFAULT 'SUM',
        time_agg TEXT NOT NULL DEFAULT 'SUM',
        nw_agg TEXT NOT NULL DEFAULT 'SUM',
        time_agg_override INTEGER NOT NULL DEFAULT 0,
        nw_agg_override INTEGER NOT NULL DEFAULT 0,
        unit TEXT,
        updated_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}dim_family (
        family TEXT NOT NULL,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        ne_type TEXT NOT NULL DEFAULT '',
        default_gp_seconds INTEGER,
        updated_at TIMESTAMPTZ,
        PRIMARY KEY (family, vendor, ne_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}agg_rule_family (
        family TEXT NOT NULL,
        ne_type TEXT NOT NULL DEFAULT '',
        time_agg TEXT NOT NULL DEFAULT 'SUM',
        nw_agg TEXT NOT NULL DEFAULT 'SUM',
        enabled INTEGER NOT NULL DEFAULT 1,
        updated_at TIMESTAMPTZ,
        PRIMARY KEY (family, ne_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}fact_values_15m (
        bucket_ts TIMESTAMPTZ NOT NULL,
        object_dn TEXT NOT NULL,
        counter_id TEXT NOT NULL,
        gp_seconds INTEGER NOT NULL DEFAULT 900,
        ne_type TEXT NOT NULL DEFAULT '',
        stream TEXT NOT NULL DEFAULT '',
        family TEXT,
        value DOUBLE PRECISION,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        sample_count INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}fact_values_hour (
        bucket_ts TIMESTAMPTZ NOT NULL,
        object_dn TEXT NOT NULL,
        counter_id TEXT NOT NULL,
        gp_seconds INTEGER NOT NULL DEFAULT 900,
        ne_type TEXT NOT NULL DEFAULT '',
        stream TEXT NOT NULL DEFAULT '',
        family TEXT,
        value DOUBLE PRECISION,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        sample_count INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}fact_values_day (
        bucket_ts TIMESTAMPTZ NOT NULL,
        object_dn TEXT NOT NULL,
        counter_id TEXT NOT NULL,
        gp_seconds INTEGER NOT NULL DEFAULT 900,
        ne_type TEXT NOT NULL DEFAULT '',
        stream TEXT NOT NULL DEFAULT '',
        family TEXT,
        value DOUBLE PRECISION,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        sample_count INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}fact_values_week (
        bucket_ts TIMESTAMPTZ NOT NULL,
        object_dn TEXT NOT NULL,
        counter_id TEXT NOT NULL,
        gp_seconds INTEGER NOT NULL DEFAULT 900,
        ne_type TEXT NOT NULL DEFAULT '',
        stream TEXT NOT NULL DEFAULT '',
        family TEXT,
        value DOUBLE PRECISION,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        sample_count INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}fact_values_month (
        bucket_ts TIMESTAMPTZ NOT NULL,
        object_dn TEXT NOT NULL,
        counter_id TEXT NOT NULL,
        gp_seconds INTEGER NOT NULL DEFAULT 900,
        ne_type TEXT NOT NULL DEFAULT '',
        stream TEXT NOT NULL DEFAULT '',
        family TEXT,
        value DOUBLE PRECISION,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        sample_count INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}fact_values_year (
        bucket_ts TIMESTAMPTZ NOT NULL,
        object_dn TEXT NOT NULL,
        counter_id TEXT NOT NULL,
        gp_seconds INTEGER NOT NULL DEFAULT 900,
        ne_type TEXT NOT NULL DEFAULT '',
        stream TEXT NOT NULL DEFAULT '',
        family TEXT,
        value DOUBLE PRECISION,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        sample_count INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}kpi_definitions (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        formula TEXT NOT NULL,
        description TEXT,
        vendor TEXT NOT NULL DEFAULT 'nokia',
        scope_default TEXT DEFAULT 'cell',
        kpi_id TEXT,
        abbreviation TEXT,
        technology TEXT,
        unit TEXT,
        measurement TEXT,
        object_levels TEXT,
        time_levels TEXT,
        source TEXT DEFAULT 'manual',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_by TEXT,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}saved_views (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        created_by TEXT,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {q}ingest_lag_snapshots (
        id BIGSERIAL PRIMARY KEY,
        captured_at TIMESTAMPTZ NOT NULL,
        lag_minutes DOUBLE PRECISION,
        backlog_files INTEGER,
        failed_files INTEGER,
        last_rop TEXT,
        detail_json TEXT
    )
    """,
]

def _sqlite_columns(conn, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _sqlite_version(conn) -> int:
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _set_sqlite_version(conn, version: int) -> None:
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(version),),
    )


def _migrate_sqlite(conn) -> None:
    """Bring existing laptop DB to SCHEMA_VERSION (fact rebuild if grain PK missing)."""
    ver = _sqlite_version(conn)
    alters = [
        ("ingest_ledger", "ne_type", "TEXT"),
        ("ingest_ledger", "shard", "TEXT"),
        ("ingest_ledger", "file_begin", "TEXT"),
        ("ingest_ledger", "file_end", "TEXT"),
        ("ingest_ledger", "gp_seconds_set", "TEXT"),
        ("dim_object", "ne_type", "TEXT"),
        ("dim_object", "mo_class", "TEXT"),
        ("dim_counter", "time_agg", "TEXT DEFAULT 'SUM'"),
        ("dim_counter", "nw_agg", "TEXT DEFAULT 'SUM'"),
        ("dim_counter", "time_agg_override", "INTEGER DEFAULT 0"),
        ("dim_counter", "nw_agg_override", "INTEGER DEFAULT 0"),
        ("kpi_definitions", "kpi_id", "TEXT"),
        ("kpi_definitions", "abbreviation", "TEXT"),
        ("kpi_definitions", "technology", "TEXT"),
        ("kpi_definitions", "unit", "TEXT"),
        ("kpi_definitions", "measurement", "TEXT"),
        ("kpi_definitions", "object_levels", "TEXT"),
        ("kpi_definitions", "time_levels", "TEXT"),
        ("kpi_definitions", "source", "TEXT DEFAULT 'manual'"),
        ("kpi_definitions", "enabled", "INTEGER DEFAULT 1"),
    ]
    for table, col, decl in alters:
        try:
            cols = _sqlite_columns(conn, table)
        except Exception:
            continue
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    for table in ("fact_values_15m", "fact_values_hour", "fact_values_day"):
        try:
            cols = _sqlite_columns(conn, table)
        except Exception:
            cols = set()
        if cols and "gp_seconds" not in cols:
            conn.execute(f"DROP TABLE IF EXISTS {table}")

    # Recreate any dropped fact tables, then indexes (columns now exist)
    conn.executescript(DDL_SQLITE_TABLES)
    conn.executescript(DDL_SQLITE_INDEXES)
    if ver < SCHEMA_VERSION:
        _set_sqlite_version(conn, SCHEMA_VERSION)


def _migrate_postgres(conn) -> None:
    prefix = f'"{config.PM_PLUS_SCHEMA}".'
    cur = conn.cursor()
    for table, col, decl in (
        ("ingest_ledger", "ne_type", "TEXT"),
        ("ingest_ledger", "shard", "TEXT"),
        ("ingest_ledger", "file_begin", "TEXT"),
        ("ingest_ledger", "file_end", "TEXT"),
        ("ingest_ledger", "gp_seconds_set", "TEXT"),
        ("dim_object", "ne_type", "TEXT"),
        ("dim_object", "mo_class", "TEXT"),
    ):
        cur.execute(
            f"ALTER TABLE {prefix}{table} ADD COLUMN IF NOT EXISTS {col} {decl}"
        )
    for table in ("fact_values_15m", "fact_values_hour", "fact_values_day"):
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s AND column_name='gp_seconds'
            """,
            (config.PM_PLUS_SCHEMA, table),
        )
        if cur.fetchone() is None:
            cur.execute(f"DROP TABLE IF EXISTS {prefix}{table} CASCADE")
    for stmt in DDL_PG_TABLES:
        cur.execute(stmt.format(q=prefix))
    cur.execute(
        f"INSERT INTO {prefix}schema_meta(key, value) VALUES('schema_version', %s) "
        f"ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
        (str(SCHEMA_VERSION),),
    )


def init_schema() -> dict:
    """Create schema/tables. Returns backend info."""
    if config.use_postgres():
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{config.PM_PLUS_SCHEMA}"')
            prefix = f'"{config.PM_PLUS_SCHEMA}".'
            for stmt in DDL_PG_TABLES:
                cur.execute(stmt.format(q=prefix))
            _migrate_postgres(conn)
            cur.execute(
                f'CREATE INDEX IF NOT EXISTS idx_pm_plus_ledger_status '
                f'ON {prefix}ingest_ledger(status)'
            )
            cur.execute(
                f'CREATE INDEX IF NOT EXISTS idx_pm_plus_fact_h_obj '
                f'ON {prefix}fact_values_hour(object_dn, bucket_ts)'
            )
            cur.execute(
                f'CREATE INDEX IF NOT EXISTS idx_pm_plus_fact_h_grain '
                f'ON {prefix}fact_values_hour(gp_seconds, ne_type, stream)'
            )
            cur.execute(
                f'CREATE INDEX IF NOT EXISTS idx_pm_plus_fact_h_ctr '
                f'ON {prefix}fact_values_hour(counter_id, bucket_ts)'
            )
            conn.commit()
        return {"backend": "postgres", "schema": config.PM_PLUS_SCHEMA, "url_set": True}

    with connect() as conn:
        # Tables first (IF NOT EXISTS keeps old rows), then column migrate, then indexes
        conn.executescript(DDL_SQLITE_TABLES)
        _migrate_sqlite(conn)
        conn.commit()
    return {
        "backend": "sqlite",
        "path": str(config.SQLITE_PATH),
        "url_set": False,
        "schema_version": SCHEMA_VERSION,
    }
