"""Discover / download / parse / write pipeline for PM Plus."""

from __future__ import annotations

import hashlib
import stat
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import paramiko

from core.pm_plus import config
from core.pm_plus.db import connect, execute, fetchone, qident
from core.pm_plus import ledger
from core.pm_plus.file_meta import (
    controller_key_from_dn,
    parse_filename,
    site_key_from_dn,
    tech_guess,
)
from core.pm_plus.agg_rules import load_time_agg_map, normalize_agg_rule
from core.pm_plus.nokia_parser import fold_samples_to_hour, iter_samples_from_path
from core.pm_plus.schema import init_schema


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _stamp_samples(samples: list, *, ne_type: str, stream: str) -> None:
    ne = (ne_type or "").upper()
    st = stream or ""
    for s in samples:
        s.ne_type = ne
        s.stream = st


def write_samples_to_db(
    samples_rop: list,
    hour_rows: dict,
) -> int:
    """Upsert ROP + hourly facts and dims. Grain keys never collapse.

    Primary key grain: (bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream).
    """
    now = _now()
    obj_tbl = "dim_object"
    ctr_tbl = "dim_counter"
    fam_tbl = "dim_family"
    f15_tbl = "fact_values_15m"
    fh_tbl = "fact_values_hour"
    conflict = "bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream"

    with connect() as conn:
        objects: dict = {}
        counters: dict = {}
        families: dict = {}
        for s in samples_rop:
            objects[s.object_dn] = s
            counters[s.counter_id] = s
            families[(s.family, s.vendor or "nokia", (s.ne_type or "").upper())] = s

        for dn, s in objects.items():
            ne = (s.ne_type or "").upper()
            execute(
                conn,
                f"INSERT INTO {obj_tbl} "
                f"(object_dn, vendor, tech, ne_type, mo_class, site_key, controller_key, base_dn, updated_at) "
                f"VALUES (?,?,?,?,?,?,?,?,?) "
                f"ON CONFLICT(object_dn) DO UPDATE SET updated_at=excluded.updated_at, "
                f"tech=COALESCE(NULLIF(excluded.tech,''), {obj_tbl}.tech), "
                f"ne_type=COALESCE(NULLIF(excluded.ne_type,''), {obj_tbl}.ne_type), "
                f"mo_class=COALESCE(NULLIF(excluded.mo_class,''), {obj_tbl}.mo_class), "
                f"site_key=COALESCE(NULLIF(excluded.site_key,''), {obj_tbl}.site_key)",
                (
                    dn,
                    s.vendor or "nokia",
                    tech_guess(dn, s.family, ne),
                    ne,
                    s.mo_class or "",
                    site_key_from_dn(dn),
                    controller_key_from_dn(dn),
                    s.managed_element or (dn.split("/")[0] if dn else ""),
                    now,
                ),
            )

        for cid, s in counters.items():
            execute(
                conn,
                f"INSERT INTO {ctr_tbl} (counter_id, vendor, family, display_name, agg_rule, "
                f"time_agg, nw_agg, updated_at) "
                f"VALUES (?,?,?,?,?,?,?,?) "
                f"ON CONFLICT(counter_id) DO UPDATE SET family=COALESCE(excluded.family, {ctr_tbl}.family), "
                f"updated_at=excluded.updated_at",
                (cid, s.vendor or "nokia", s.family, cid, "SUM", "SUM", "SUM", now),
            )

        for (fam, vendor, ne), s in families.items():
            if not fam:
                continue
            execute(
                conn,
                f"INSERT INTO {fam_tbl} (family, vendor, ne_type, default_gp_seconds, updated_at) "
                f"VALUES (?,?,?,?,?) "
                f"ON CONFLICT(family, vendor, ne_type) DO UPDATE SET "
                f"default_gp_seconds=COALESCE(excluded.default_gp_seconds, {fam_tbl}.default_gp_seconds), "
                f"updated_at=excluded.updated_at",
                (fam, vendor, ne, int(s.gp_seconds or 900), now),
            )

        for s in samples_rop:
            if not s.bucket_ts:
                continue
            execute(
                conn,
                f"INSERT INTO {f15_tbl} "
                f"(bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream, family, value, vendor, sample_count) "
                f"VALUES (?,?,?,?,?,?,?,?,?,1) "
                f"ON CONFLICT({conflict}) DO UPDATE SET "
                f"value = COALESCE({f15_tbl}.value, 0) + COALESCE(excluded.value, 0), "
                f"sample_count = {f15_tbl}.sample_count + 1, "
                f"family = COALESCE(excluded.family, {f15_tbl}.family)",
                (
                    s.bucket_ts,
                    s.object_dn,
                    s.counter_id,
                    int(s.gp_seconds or 900),
                    (s.ne_type or "").upper(),
                    s.stream or "",
                    s.family,
                    s.value,
                    s.vendor or "nokia",
                ),
            )

        rules = load_time_agg_map(counters.keys())
        for row in hour_rows.values():
            rule = rules.get(row["counter_id"], "SUM")
            rule = normalize_agg_rule(rule)
            weight = float(row.get("weight") or row.get("sample_count") or 0)
            if weight <= 0 and row.get("min_value") is None:
                continue
            if rule == "AVG":
                value = float(row["sum_value"]) / weight if weight else None
            elif rule == "MAX":
                value = row.get("max_value")
            elif rule == "MIN":
                value = row.get("min_value")
            else:
                value = row.get("sum_value")
            if value is None:
                continue
            execute(
                conn,
                f"INSERT INTO {fh_tbl} "
                f"(bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream, family, value, vendor, sample_count) "
                f"VALUES (?,?,?,?,?,?,?,?,?,?) "
                f"ON CONFLICT({conflict}) DO UPDATE SET "
                f"value = excluded.value, "
                f"sample_count = excluded.sample_count, "
                f"family = COALESCE(excluded.family, {fh_tbl}.family)",
                (
                    row["bucket_ts"],
                    row["object_dn"],
                    row["counter_id"],
                    int(row.get("gp_seconds") or 900),
                    (row.get("ne_type") or "").upper(),
                    row.get("stream") or "",
                    row["family"],
                    value,
                    row["vendor"],
                    int(weight),
                ),
            )
        conn.commit()
    return len(hour_rows)


def ingest_local_file(
    path: Path | str,
    *,
    vendor: str = "nokia",
    host: str = "local",
    stream: str = "local",
    bucket: str = "local",
    relpath: str | None = None,
) -> dict:
    """Parse one local file into the warehouse with full grain tagging."""
    init_schema()
    path = Path(path)
    relpath = relpath or path.name
    meta = parse_filename(Path(relpath).name)
    t0 = time.perf_counter()
    samples = list(iter_samples_from_path(path))
    _stamp_samples(samples, ne_type=meta.ne_type, stream=stream)
    t_parse = time.perf_counter()
    hour_rows = fold_samples_to_hour(samples)
    rows = write_samples_to_db(samples, hour_rows)
    t_write = time.perf_counter()
    digest = file_sha256(path)

    gp_set = sorted({int(s.gp_seconds or 900) for s in samples})
    file_begin = min((s.bucket_ts for s in samples if s.bucket_ts), default="")
    file_end = max((s.bucket_ts for s in samples if s.bucket_ts), default="")

    ledger.upsert_discovered(
        vendor=vendor,
        host=host,
        stream=stream,
        bucket=bucket,
        relpath=relpath,
        size_bytes=path.stat().st_size,
        mtime_epoch=path.stat().st_mtime,
        ne_type=meta.ne_type,
        shard=meta.shard,
    )
    with connect() as conn:
        row = fetchone(
            conn,
            f"SELECT id FROM {qident('ingest_ledger')} "
            f"WHERE vendor=? AND host=? AND stream=? AND bucket=? AND relpath=?",
            (vendor, host, stream, bucket, relpath),
        )
    if row:
        ledger.mark_status(
            int(row["id"]),
            "done",
            local_path=str(path),
            rows_written=rows,
            content_hash=digest,
            ne_type=meta.ne_type,
            shard=meta.shard,
            file_begin=file_begin,
            file_end=file_end,
            gp_seconds_set=",".join(str(x) for x in gp_set),
        )

    return {
        "path": str(path),
        "samples_15m": len(samples),
        "samples_rop": len(samples),
        "hour_rows": rows,
        "objects": len({s.object_dn for s in samples}),
        "counters": len({s.counter_id for s in samples}),
        "families": sorted({s.family for s in samples}),
        "ne_type": meta.ne_type,
        "shard": meta.shard,
        "stream": stream,
        "gp_seconds_set": gp_set,
        "parse_seconds": round(t_parse - t0, 3),
        "write_seconds": round(t_write - t_parse, 3),
        "total_seconds": round(t_write - t0, 3),
        "sha256": digest,
        "backend": "postgres" if config.use_postgres() else "sqlite",
    }


def _ssh_connect(host_cfg: dict):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=host_cfg["host"],
        port=int(host_cfg.get("port") or 22),
        username=host_cfg.get("username") or "",
        password=host_cfg.get("password") or "",
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    return ssh, ssh.open_sftp()


def _pick_host() -> dict:
    last_err = None
    for host_cfg in config.ftp_hosts():
        if not host_cfg.get("password"):
            last_err = f"No password for {host_cfg['host']}"
            continue
        try:
            ssh, sftp = _ssh_connect(host_cfg)
            sftp.close()
            ssh.close()
            return host_cfg
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
    raise RuntimeError(f"No reachable Nokia PM FTP host ({last_err})")


def discover_remote_files(*, max_buckets_per_stream: int = 4) -> list[dict]:
    """List newest ROP buckets/files and upsert ledger discovered rows."""
    init_schema()
    host_cfg = _pick_host()
    ssh, sftp = _ssh_connect(host_cfg)
    found = []
    try:
        for stream, remote_root in config.REMOTE_PATHS.items():
            remote_root = remote_root.rstrip("/") + "/"
            try:
                entries = sftp.listdir_attr(remote_root)
            except OSError:
                continue
            buckets = [e for e in entries if stat.S_ISDIR(e.st_mode)]
            buckets.sort(key=lambda e: e.st_mtime or 0, reverse=True)
            for b in buckets[:max_buckets_per_stream]:
                bucket = b.filename
                bpath = f"{remote_root}{bucket}"
                try:
                    files = sftp.listdir_attr(bpath)
                except OSError:
                    continue
                for f in files:
                    if stat.S_ISDIR(f.st_mode):
                        continue
                    name = f.filename
                    low = name.lower()
                    if not (low.endswith(".gz") or low.endswith(".xml")):
                        continue
                    fmeta = parse_filename(name)
                    ledger.upsert_discovered(
                        vendor="nokia",
                        host=host_cfg["host"],
                        stream=stream,
                        bucket=bucket,
                        relpath=name,
                        size_bytes=int(f.st_size or 0),
                        mtime_epoch=float(f.st_mtime or 0),
                        ne_type=fmeta.ne_type,
                        shard=fmeta.shard,
                    )
                    found.append(
                        {
                            "host": host_cfg["host"],
                            "stream": stream,
                            "bucket": bucket,
                            "relpath": name,
                            "ne_type": fmeta.ne_type,
                            "shard": fmeta.shard,
                            "remote_full_path": f"{bpath}/{name}",
                            "size_bytes": int(f.st_size or 0),
                        }
                    )
    finally:
        sftp.close()
        ssh.close()
    return found


def download_file(host_cfg: dict, remote_full_path: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ssh, sftp = _ssh_connect(host_cfg)
    try:
        sftp.get(remote_full_path, str(dest))
    finally:
        sftp.close()
        ssh.close()
    return dest


def process_claimed_row(row: dict, host_cfg: dict | None = None) -> dict:
    """Download (if needed) + ingest one ledger row."""
    ledger.mark_status(int(row["id"]), "in_progress")
    host_cfg = host_cfg or next(
        (h for h in config.ftp_hosts() if h["host"] == row["host"]),
        None,
    )
    if host_cfg is None:
        host_cfg = _pick_host()

    remote_root = config.REMOTE_PATHS.get(str(row["stream"]), "").rstrip("/")
    remote_full = f"{remote_root}/{row['bucket']}/{row['relpath']}"
    dest = (
        config.STAGING_DIR
        / str(row["host"])
        / str(row["stream"])
        / str(row["bucket"])
        / str(row["relpath"])
    )
    try:
        if not dest.exists():
            download_file(host_cfg, remote_full, dest)
        result = ingest_local_file(
            dest,
            vendor=row.get("vendor") or "nokia",
            host=row["host"],
            stream=row["stream"],
            bucket=row["bucket"],
            relpath=row["relpath"],
        )
        if config.DELETE_LOCAL_AFTER_INGEST:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        ledger.mark_status(int(row["id"]), "failed", error_message=str(exc)[:2000])
        return {"ok": False, "error": str(exc), "id": row["id"]}


def run_ingest_cycle(
    *,
    max_buckets_per_stream: int = 2,
    claim_limit: int | None = None,
    download_workers: int | None = None,
) -> dict:
    """One discover → claim → parallel process cycle."""
    init_schema()
    discovered = discover_remote_files(max_buckets_per_stream=max_buckets_per_stream)
    claimed = ledger.claim_next(limit=claim_limit or max(16, config.INGEST_WORKERS * 4))
    workers = download_workers or config.DOWNLOAD_WORKERS
    results = []
    if claimed:
        host_cfg = _pick_host()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(process_claimed_row, row, host_cfg): row for row in claimed}
            for fut in as_completed(futs):
                results.append(fut.result())
    snap = ledger.record_lag_snapshot(
        {"discovered": len(discovered), "claimed": len(claimed), "processed": len(results)}
    )
    ok = sum(1 for r in results if r.get("ok"))
    return {
        "discovered": len(discovered),
        "claimed": len(claimed),
        "ok": ok,
        "failed": len(results) - ok,
        "lag": snap,
    }
