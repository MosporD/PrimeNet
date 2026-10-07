"""Postgres identifier truncation helpers used by PM loaders."""

from db.runtime import postgres_ident_truncate


def test_short_name_unchanged():
    assert postgres_ident_truncate("LNCEL name") == "LNCEL name"


def test_long_nokia_kpi_truncated_to_63_bytes():
    full = (
        "Number of Signaling Connection Establishment Requests rejected  "
        "due to lack of PUCCH resources"
    )
    trunc = postgres_ident_truncate(full)
    assert len(full.encode("utf-8")) > 63
    assert len(trunc.encode("utf-8")) <= 63
    assert full.startswith(trunc.rstrip()) or trunc == full[: len(trunc)]


def test_utf8_safe_truncation():
    # Multi-byte chars near the boundary must not raise.
    name = "x" * 60 + "ééé"
    out = postgres_ident_truncate(name)
    out.encode("utf-8")  # must be valid
    assert len(out.encode("utf-8")) <= 63
