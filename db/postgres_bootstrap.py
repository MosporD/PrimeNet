"""
Create PostgreSQL schemas and tables (one server, four schemas).

Run via ``sync.db_migration.run_migrations()`` when ``DB_ENGINE=postgresql``.
"""

from __future__ import annotations

import logging
import os
import sys

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_config import (
    DATABASE_URL,
    PM_TECHNOLOGIES,
    SCHEMA_APP,
    SCHEMA_HUAWEI_PM,
    SCHEMA_METADATA,
    SCHEMA_NOKIA_PM,
    pm_table_name,
)

logger = logging.getLogger(__name__)


def _exec(cur, sql: str):
    cur.execute(sql)


def _create_app_user_tables(cur):
    """Tables from ``database_enhanced.init_db`` (ncm_users.db) in schema ``app``."""
    A = SCHEMA_APP
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            department TEXT,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            password_changed_at TIMESTAMP,
            force_password_change BOOLEAN DEFAULT TRUE,
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES {A}.users(id),
            session_token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.activity_log (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES {A}.users(id),
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.tasks (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            task_type TEXT NOT NULL,
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'pending',
            created_by INTEGER NOT NULL REFERENCES {A}.users(id),
            assigned_to INTEGER REFERENCES {A}.users(id),
            xml_file_path TEXT,
            xml_file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.task_updates (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES {A}.tasks(id),
            user_id INTEGER NOT NULL REFERENCES {A}.users(id),
            update_type TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.filter_profiles (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES {A}.users(id),
            profile_name TEXT NOT NULL,
            description TEXT,
            filter_data TEXT NOT NULL,
            is_shared BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, profile_name)
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.config_versions (
            id SERIAL PRIMARY KEY,
            ne_name TEXT NOT NULL,
            file_name TEXT NOT NULL,
            version_num INTEGER NOT NULL,
            xml_content TEXT NOT NULL,
            comment TEXT,
            uploaded_by INTEGER NOT NULL REFERENCES {A}.users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.report_archive (
            id SERIAL PRIMARY KEY,
            report_name TEXT NOT NULL,
            report_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            generated_by INTEGER NOT NULL REFERENCES {A}.users(id),
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.user_preferences (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES {A}.users(id),
            preferences TEXT NOT NULL DEFAULT '{{}}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.config_scheduler_tasks (
            id SERIAL PRIMARY KEY,
            task_name TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT 'mixed',
            schedule_mode TEXT NOT NULL DEFAULT 'run_now',
            scheduled_at TIMESTAMP,
            run_mode TEXT NOT NULL DEFAULT 'serial',
            execution_order TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            completion_notes TEXT,
            created_by INTEGER NOT NULL REFERENCES {A}.users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.config_scheduler_task_files (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES {A}.config_scheduler_tasks(id) ON DELETE CASCADE,
            original_file_name TEXT NOT NULL,
            stored_file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_order INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {A}.config_scheduler_result_files (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES {A}.config_scheduler_tasks(id) ON DELETE CASCADE,
            original_file_name TEXT NOT NULL,
            stored_file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_by INTEGER NOT NULL REFERENCES {A}.users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')


def bootstrap():
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL is required when DB_ENGINE=postgresql')

    from sync.db_migration import PER_TECH_CSV_SCHEMA  # local import avoids cycles

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    for schema in (SCHEMA_APP, SCHEMA_METADATA, SCHEMA_NOKIA_PM, SCHEMA_HUAWEI_PM):
        _exec(cur, f'CREATE SCHEMA IF NOT EXISTS {schema}')

    # ── metadata.sites / cells / sectors ───────────────────────────────────
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {SCHEMA_METADATA}.sites (
            site_id    TEXT PRIMARY KEY,
            site_name  TEXT NOT NULL,
            latitude   DOUBLE PRECISION,
            longitude  DOUBLE PRECISION,
            region     TEXT,
            site_type  TEXT,
            vendor     TEXT,
            status     TEXT DEFAULT 'Active',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {SCHEMA_METADATA}.cells (
            cell_id         SERIAL PRIMARY KEY,
            cell_name       TEXT    NOT NULL UNIQUE,
            site_id         TEXT REFERENCES {SCHEMA_METADATA}.sites(site_id),
            technology      TEXT,
            vendor          TEXT,
            frequency_band  TEXT,
            azimuth         DOUBLE PRECISION,
            mechanical_tilt DOUBLE PRECISION,
            electrical_tilt DOUBLE PRECISION,
            pci             INTEGER,
            status          TEXT DEFAULT 'Active',
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {SCHEMA_METADATA}.sectors (
            sector_id       SERIAL PRIMARY KEY,
            site_id         TEXT REFERENCES {SCHEMA_METADATA}.sites(site_id),
            sector_name     TEXT,
            technology      TEXT,
            frequency_band  TEXT,
            azimuth         DOUBLE PRECISION,
            mechanical_tilt DOUBLE PRECISION,
            electrical_tilt DOUBLE PRECISION,
            vendor          TEXT,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    _exec(cur, f'CREATE INDEX IF NOT EXISTS idx_cells_site ON {SCHEMA_METADATA}.cells(site_id)')
    _exec(cur, f'CREATE INDEX IF NOT EXISTS idx_cells_vendor ON {SCHEMA_METADATA}.cells(vendor)')
    _exec(cur, f'CREATE INDEX IF NOT EXISTS idx_cells_tech ON {SCHEMA_METADATA}.cells(technology)')
    _exec(cur, f'CREATE INDEX IF NOT EXISTS idx_sectors_site ON {SCHEMA_METADATA}.sectors(site_id)')

    # Per-tech CSV mirror tables
    for table, csv_cols in PER_TECH_CSV_SCHEMA.items():
        coldefs = ['cell_name TEXT PRIMARY KEY']
        for c in csv_cols:
            if c == 'cell_name':
                continue
            coldefs.append(f'"{c}" TEXT')
        coldefs.append('technology TEXT')
        coldefs.append('updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        body = ', '.join(coldefs)
        _exec(cur, f'CREATE TABLE IF NOT EXISTS {SCHEMA_METADATA}."{table}" ({body})')
        _exec(
            cur,
            f'CREATE INDEX IF NOT EXISTS "idx_{table}_technology" ON {SCHEMA_METADATA}."{table}" (technology)',
        )

    # PM hourly KPI tables (Nokia). Huawei PM tables are created per sheet on ingest.
    for tech in PM_TECHNOLOGIES:
        tbl = pm_table_name(tech)
        _exec(cur, f'''
            CREATE TABLE IF NOT EXISTS {SCHEMA_NOKIA_PM}."{tbl}" (
                id SERIAL PRIMARY KEY,
                cell_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                UNIQUE (cell_name, timestamp)
            )
        ''')
        _exec(
            cur,
            f'CREATE INDEX IF NOT EXISTS "idx_{tbl}_cell_ts" ON {SCHEMA_NOKIA_PM}."{tbl}" (cell_name, timestamp)',
        )
        _exec(
            cur,
            f'CREATE INDEX IF NOT EXISTS "idx_{tbl}_ts" ON {SCHEMA_NOKIA_PM}."{tbl}" (timestamp)',
        )

    _create_app_user_tables(cur)

    _exec(cur, f'''
        CREATE TABLE IF NOT EXISTS {SCHEMA_APP}.sync_log (
            id            SERIAL PRIMARY KEY,
            sync_type     TEXT NOT NULL,
            technology    TEXT NOT NULL,
            status        TEXT NOT NULL,
            rows_affected INTEGER DEFAULT 0,
            message       TEXT,
            started_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cur.close()
    conn.close()
    logger.info('PostgreSQL schemas and base tables are ready.')
