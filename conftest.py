"""Pytest session setup.

The unit tests exercise pure logic, but importing most modules pulls in
``db.runtime``, whose connect helpers call ``require_activation()``. Without
these flags a bare checkout fails collection with ``ActivationRequired`` rather
than running the tests, which is why the suite could not run in CI.

Set before any test module is imported; the activation gate reads the
environment lazily, so this is enough to keep the product gate itself intact.
"""

import os

os.environ.setdefault("NCM_SKIP_ACTIVATION", "1")
os.environ.setdefault("NCM_BOOTSTRAP_ON_IMPORT", "0")
os.environ.setdefault("NCM_DISABLE_SCHEDULER", "1")
os.environ.setdefault("FLASK_SECRET_KEY", "pytest-fixed-secret")


# --- Hermetic Postgres schemas for tests that point a store at a temp path -----------------
# The runtime is Postgres-only: a store path only works if it is one of the canonical
# SQLite paths mapped to a schema in db.pg_domains. Tests that monkeypatch a store (or the
# users DB) to a tmp file would therefore fail with "No Postgres schema mapped". Give each
# such tmp path its own throwaway schema instead, and drop them when the session ends.
# This must run before any test module binds ``schema_for_sqlite_path`` by name.
import hashlib  # noqa: E402
import tempfile  # noqa: E402

import db.pg_domains as _pg_domains  # noqa: E402

_REAL_SCHEMA_FOR_PATH = _pg_domains.schema_for_sqlite_path
_TEST_SCHEMAS: set[str] = set()


def _schema_for_test_path(path):
    schema = _REAL_SCHEMA_FOR_PATH(path)
    if schema or not path or not _pg_domains.url_is_postgres():
        return schema
    try:
        norm = os.path.normcase(os.path.realpath(str(path)))
        tmp_root = os.path.normcase(os.path.realpath(tempfile.gettempdir()))
    except (OSError, TypeError, ValueError):
        return schema
    if not norm.startswith(tmp_root + os.sep):
        return schema
    name = "t_" + hashlib.sha1(norm.encode()).hexdigest()[:16]
    _TEST_SCHEMAS.add(name)
    return name


_pg_domains.schema_for_sqlite_path = _schema_for_test_path

# db.runtime binds the name at import time, so repoint it as well.
import db.runtime as _db_runtime  # noqa: E402

_db_runtime.schema_for_sqlite_path = _schema_for_test_path


def pytest_sessionfinish(session, exitstatus):
    if not _TEST_SCHEMAS or not _pg_domains.url_is_postgres():
        return
    try:
        import psycopg

        with psycopg.connect(_pg_domains.postgres_url(), connect_timeout=10, autocommit=True) as conn:
            for name in sorted(_TEST_SCHEMAS):
                conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
    except Exception:  # best-effort cleanup; never fail the run over it
        pass
