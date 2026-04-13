"""Database runtime: SQLite (dev) or PostgreSQL (deployment)."""

from db.runtime import (
    adapt_placeholders,
    connect_app,
    connect_huawei_pm,
    connect_metadata,
    connect_nokia_pm,
    is_postgresql,
    postgres_table_columns,
    quote_ident,
)

__all__ = [
    'adapt_placeholders',
    'connect_app',
    'connect_huawei_pm',
    'connect_metadata',
    'connect_nokia_pm',
    'is_postgresql',
    'postgres_table_columns',
    'quote_ident',
]
