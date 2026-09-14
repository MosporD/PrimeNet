"""Idempotent ingest ledger operations."""

from __future__ import annotations

from datetime import datetime, timezone

from core.pm_plus.db import connect, execute, fetchall, fetchone, qident


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def upsert_discovered(
    *,
    vendor: str,
    host: str,
    stream: str,
    bucket: str,
    relpath: str,
    size_bytes: int | None,
    mtime_epoch: float | None,
    ne_type: str | None = None,
    shard: str | None = None,
) -> None:
    t = qident("ingest_ledger")
    now = _now()
    with connect() as conn:
        row = fetchone(
            conn,
            f"SELECT id, status, size_bytes, mtime_epoch FROM {t} "
            f"WHERE vendor=? AND host=? AND stream=? AND bucket=? AND relpath=?",
            (vendor, host, stream, bucket, relpath),
        )
        if row:
            if row["status"] in ("done", "in_progress", "claimed"):
                if (
                    size_bytes is not None
                    and row.get("size_bytes") == size_bytes
                    and (
                        mtime_epoch is None
                        or abs(float(row.get("mtime_epoch") or 0) - float(mtime_epoch)) < 0.5
                    )
                ):
                    return
            execute(
                conn,
                f"UPDATE {t} SET size_bytes=?, mtime_epoch=?, status='discovered', "
                f"error_message=NULL, discovered_at=?, "
                f"ne_type=COALESCE(?, ne_type), shard=COALESCE(?, shard) "
                f"WHERE vendor=? AND host=? AND stream=? AND bucket=? AND relpath=?",
                (
                    size_bytes,
                    mtime_epoch,
                    now,
                    ne_type,
                    shard,
                    vendor,
                    host,
                    stream,
                    bucket,
                    relpath,
                ),
            )
        else:
            execute(
                conn,
                f"INSERT INTO {t} (vendor, host, stream, bucket, relpath, size_bytes, "
                f"mtime_epoch, status, discovered_at, ne_type, shard) "
                f"VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    vendor,
                    host,
                    stream,
                    bucket,
                    relpath,
                    size_bytes,
                    mtime_epoch,
                    "discovered",
                    now,
                    ne_type,
                    shard,
                ),
            )
        conn.commit()


def claim_next(limit: int = 32) -> list[dict]:
    """Claim discovered rows for processing (best-effort, single-node)."""
    t = qident("ingest_ledger")
    now = _now()
    with connect() as conn:
        rows = fetchall(
            conn,
            f"SELECT * FROM {t} WHERE status='discovered' "
            f"ORDER BY discovered_at ASC LIMIT ?",
            (limit,),
        )
        claimed = []
        for row in rows:
            execute(
                conn,
                f"UPDATE {t} SET status='claimed', claimed_at=? WHERE id=? AND status='discovered'",
                (now, row["id"]),
            )
            row["status"] = "claimed"
            claimed.append(row)
        conn.commit()
        return claimed


def mark_status(
    ledger_id: int,
    status: str,
    *,
    error_message: str | None = None,
    local_path: str | None = None,
    rows_written: int | None = None,
    content_hash: str | None = None,
    ne_type: str | None = None,
    shard: str | None = None,
    file_begin: str | None = None,
    file_end: str | None = None,
    gp_seconds_set: str | None = None,
) -> None:
    t = qident("ingest_ledger")
    now = _now()
    sets = ["status=?"]
    params: list = [status]
    if status == "in_progress":
        sets.append("started_at=?")
        params.append(now)
    if status in ("done", "failed"):
        sets.append("finished_at=?")
        params.append(now)
    if error_message is not None:
        sets.append("error_message=?")
        params.append(error_message)
    if local_path is not None:
        sets.append("local_path=?")
        params.append(local_path)
    if rows_written is not None:
        sets.append("rows_written=?")
        params.append(rows_written)
    if content_hash is not None:
        sets.append("content_hash=?")
        params.append(content_hash)
    if ne_type is not None:
        sets.append("ne_type=?")
        params.append(ne_type)
    if shard is not None:
        sets.append("shard=?")
        params.append(shard)
    if file_begin is not None:
        sets.append("file_begin=?")
        params.append(file_begin)
    if file_end is not None:
        sets.append("file_end=?")
        params.append(file_end)
    if gp_seconds_set is not None:
        sets.append("gp_seconds_set=?")
        params.append(gp_seconds_set)
    params.append(ledger_id)
    with connect() as conn:
        execute(conn, f"UPDATE {t} SET {', '.join(sets)} WHERE id=?", tuple(params))
        conn.commit()


def health_snapshot() -> dict:
    t = qident("ingest_ledger")
    with connect() as conn:
        counts = fetchall(
            conn,
            f"SELECT status, COUNT(*) AS n FROM {t} GROUP BY status",
        )
        by_status = {r["status"]: int(r["n"]) for r in counts}
        last = fetchone(
            conn,
            f"SELECT bucket, stream, finished_at FROM {t} WHERE status='done' "
            f"ORDER BY finished_at DESC LIMIT 1",
        )
        oldest_open = fetchone(
            conn,
            f"SELECT discovered_at, bucket FROM {t} "
            f"WHERE status IN ('discovered','claimed','in_progress') "
            f"ORDER BY discovered_at ASC LIMIT 1",
        )
        by_ne = fetchall(
            conn,
            f"SELECT COALESCE(ne_type,'(unknown)') AS ne_type, COUNT(*) AS n "
            f"FROM {t} GROUP BY COALESCE(ne_type,'(unknown)')",
        )
    lag_minutes = None
    if oldest_open and oldest_open.get("discovered_at"):
        try:
            ts = str(oldest_open["discovered_at"]).replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            lag_minutes = (
                datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
            ).total_seconds() / 60.0
        except ValueError:
            lag_minutes = None
    backlog = sum(by_status.get(s, 0) for s in ("discovered", "claimed", "in_progress"))
    return {
        "by_status": by_status,
        "by_ne_type": {r["ne_type"]: int(r["n"]) for r in by_ne},
        "backlog_files": backlog,
        "failed_files": by_status.get("failed", 0),
        "lag_minutes": lag_minutes,
        "last_rop": f"{last['stream']}/{last['bucket']}" if last else None,
        "oldest_open_bucket": oldest_open.get("bucket") if oldest_open else None,
    }


def record_lag_snapshot(detail: dict | None = None) -> dict:
    import json

    snap = health_snapshot()
    t = qident("ingest_lag_snapshots")
    now = _now()
    with connect() as conn:
        execute(
            conn,
            f"INSERT INTO {t} (captured_at, lag_minutes, backlog_files, failed_files, last_rop, detail_json) "
            f"VALUES (?,?,?,?,?,?)",
            (
                now,
                snap.get("lag_minutes"),
                snap.get("backlog_files"),
                snap.get("failed_files"),
                snap.get("last_rop"),
                json.dumps(detail or snap),
            ),
        )
        conn.commit()
    snap["captured_at"] = now
    return snap
