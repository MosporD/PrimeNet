"""
Poll remote PM / metadata / femto paths for newer files than last run; if changed, pull + load.

Default: sleep 30 minutes (1800 s) between cycles unless overridden. Safe with incremental loaders:
uses individual pull scripts (no raw folder wipe).

Run as a long-lived service:
  python scripts/pipeline/watch_remote_new_files_and_pull.py

One-shot (single probe + optional pulls):
  python scripts/pipeline/watch_remote_new_files_and_pull.py --once

When the Flask app starts, ``sync.scheduler.start_scheduler`` also registers this script with
``--once`` on the same interval (``WATCH_POLL_INTERVAL_SEC``), unless
``NCM_DISABLE_SCHEDULER=1`` or ``NCM_DISABLE_PULL_WATCHER=1``.

Environment:
  WATCH_POLL_INTERVAL_SEC — seconds between cycles (default 1800 = 30 minutes).
  WATCH_STATE_FILE — override JSON state path (default: databases/admin/pull_watch_state.json).
  WATCH_ALWAYS_RUN — when true, run all pull/load pipelines every cycle (default: false).
  WATCH_VERIFY_DB_INGEST — after pull/load, re-run scope if raw files remain but DB did not advance (default: true).
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import paramiko  # noqa: E402

from sync_config import (  # noqa: E402
    ADMIN_DB_DIR,
    HUAWEI_GROUPS_DAILY_SERVER,
    HUAWEI_GROUPS_SERVER,
    HUAWEI_PM_DAILY_SERVER,
    HUAWEI_PM_SERVER,
    METADATA_SERVER,
    NOKIA_GROUPS_DAILY_SERVER,
    NOKIA_GROUPS_SERVER,
    NOKIA_PM_DAILY_SERVER,
    NOKIA_PM_SERVER,
    PROJECT_ROOT,
)

ALLOWED = (".xlsx", ".xls", ".xlsm", ".csv", ".zip", ".tgz")

# Sleep between watch cycles when not using --once (30 minutes).
DEFAULT_WATCH_POLL_INTERVAL_SEC = 30 * 60

DEFAULT_STATE = Path(ADMIN_DB_DIR) / "pull_watch_state.json"
SCRIPTS = Path(PROJECT_ROOT) / "scripts"

# Femto SFTP (same as scripts/pipeline/pull_femto_raw.py)
FEMTO_SFTP = {
    "host": "10.253.92.68",
    "port": 22,
    "username": "ftpuser",
    "password": "SmallCells@@25",
    "remote_root": "/femto/stats/",
}


def _env_int(key: str, default: int) -> int:
    try:
        raw = os.getenv(key)
        if raw is None or str(raw).strip() == "":
            return default
        return int(str(raw).strip())
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _connect(host: str, port: int, username: str, password: str):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=host, port=port, username=username, password=password, timeout=30)
    return ssh, ssh.open_sftp()


def _search_dirs(sftp, remote_dir: str, descend: bool) -> list[str]:
    out = [remote_dir]
    if not descend:
        return out
    try:
        entries = sftp.listdir_attr(remote_dir)
    except OSError:
        return out
    subdirs = [e for e in entries if stat.S_ISDIR(e.st_mode)]
    subdirs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
    for sd in subdirs:
        out.append(f"{remote_dir.rstrip('/')}/{sd.filename}")
    return out


def _sig_latest_in_remote(
    sftp,
    remote_dir: str,
    descend: bool,
    exts: tuple[str, ...] = ALLOWED,
) -> str:
    best = None  # (mtime, size, relpath)
    for d in _search_dirs(sftp, remote_dir, descend):
        try:
            entries = sftp.listdir_attr(d)
        except OSError:
            continue
        for e in entries:
            if stat.S_ISDIR(e.st_mode):
                continue
            low = e.filename.lower()
            if not low.endswith(exts):
                continue
            mt = float(e.st_mtime or 0)
            sz = int(e.st_size or 0)
            full = f"{d.rstrip('/')}/{e.filename}"
            if best is None or mt > best[0]:
                best = (mt, sz, full)
    if not best:
        return ""
    return f"{best[0]:.0f}|{best[2]}|{best[1]}"


def _sig_nokia_per_tech_dirs(sftp, server_cfg: dict, dirs_key: str) -> str:
    parts: list[str] = []
    descend = bool(server_cfg.get("descend_into_newest_subdir", False))
    for tech in sorted((server_cfg.get(dirs_key) or {}).keys()):
        rd = server_cfg[dirs_key][tech]
        parts.append(f"{tech}:{_sig_latest_in_remote(sftp, rd, descend)}")
    return "||".join(parts)


def _sig_metadata(sftp) -> str:
    root_dir = METADATA_SERVER.get("root_dir", "/")
    try:
        entries = sftp.listdir_attr(root_dir)
    except OSError:
        return ""
    subdirs = [e for e in entries if stat.S_ISDIR(e.st_mode)]
    if not subdirs:
        return ""
    subdirs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
    latest = f"{root_dir.rstrip('/')}/{subdirs[0].filename}"
    try:
        files = sftp.listdir_attr(latest)
    except OSError:
        return latest
    csvs = [e for e in files if not stat.S_ISDIR(e.st_mode) and e.filename.lower().endswith(".csv")]
    csvs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
    top = csvs[:5]
    tail = ":".join(f"{e.filename}:{e.st_mtime or 0}:{e.st_size or 0}" for e in top)
    return f"{latest}|{tail}"


def _femto_remote_tree_sig(sftp, remote_root: str) -> str:
    """Max mtime + count of .tgz under remote_root (recursive)."""
    from stat import S_ISDIR

    best_mt = 0.0
    count = 0

    def walk(rdir: str) -> None:
        nonlocal best_mt, count
        try:
            for entry in sftp.listdir_attr(rdir):
                rp = f"{rdir.rstrip('/')}/{entry.filename}"
                if S_ISDIR(entry.st_mode):
                    walk(rp)
                elif entry.filename.lower().endswith(".tgz"):
                    count += 1
                    best_mt = max(best_mt, float(entry.st_mtime or 0))
        except OSError:
            return

    walk(remote_root)
    return f"{best_mt:.0f}|n={count}"


def _load_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _run(script: str, args: list[str] | None = None) -> int:
    cmd = [sys.executable, str(SCRIPTS / script)] + (args or [])
    print(f"[watch] run: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return int(proc.returncode or 0)


def _probe_all() -> dict[str, str]:
    out: dict[str, str] = {}

    # --- Hourly Huawei ---
    h = HUAWEI_PM_SERVER
    if str(h.get("host") or "").strip():
        ssh, sftp = _connect(h["host"], h.get("port", 22), h.get("username", ""), h.get("password", ""))
        try:
            out["hourly_huawei_cells"] = _sig_latest_in_remote(
                sftp, h["remote_dir"], bool(h.get("descend_into_newest_subdir", False))
            )
            g = HUAWEI_GROUPS_SERVER
            out["hourly_huawei_groups"] = _sig_latest_in_remote(
                sftp, g["remote_dir"], bool(g.get("descend_into_newest_subdir", False))
            )
        finally:
            sftp.close()
            ssh.close()

    # --- Hourly Nokia ---
    n = NOKIA_PM_SERVER
    if str(n.get("host") or "").strip():
        ssh, sftp = _connect(n["host"], n.get("port", 22), n.get("username", ""), n.get("password", ""))
        try:
            out["hourly_nokia_cells"] = _sig_nokia_per_tech_dirs(sftp, n, "dirs")
            out["hourly_nokia_groups"] = _sig_nokia_per_tech_dirs(sftp, NOKIA_GROUPS_SERVER, "dirs")
        finally:
            sftp.close()
            ssh.close()

    # --- Metadata ---
    m = METADATA_SERVER
    if str(m.get("host") or "").strip():
        ssh, sftp = _connect(m["host"], m.get("port", 22), m.get("username", ""), m.get("password", ""))
        try:
            out["metadata"] = _sig_metadata(sftp)
        finally:
            sftp.close()
            ssh.close()

    # --- Daily Huawei (reuse hourly host) ---
    hd = HUAWEI_PM_DAILY_SERVER
    if str(hd.get("host") or "").strip():
        ssh, sftp = _connect(hd["host"], hd.get("port", 22), hd.get("username", ""), hd.get("password", ""))
        try:
            out["daily_huawei_cells"] = _sig_latest_in_remote(
                sftp, hd["remote_dir"], bool(hd.get("descend_into_newest_subdir", False))
            )
            gd = HUAWEI_GROUPS_DAILY_SERVER
            out["daily_huawei_groups"] = _sig_latest_in_remote(
                sftp, gd["remote_dir"], bool(gd.get("descend_into_newest_subdir", False))
            )
        finally:
            sftp.close()
            ssh.close()

    # --- Daily Nokia ---
    nd = NOKIA_PM_DAILY_SERVER
    if str(nd.get("host") or "").strip():
        ssh, sftp = _connect(nd["host"], nd.get("port", 22), nd.get("username", ""), nd.get("password", ""))
        try:
            out["daily_nokia_cells"] = _sig_nokia_per_tech_dirs(sftp, nd, "dirs")
            out["daily_nokia_groups"] = _sig_nokia_per_tech_dirs(
                sftp, NOKIA_GROUPS_DAILY_SERVER, "dirs"
            )
        finally:
            sftp.close()
            ssh.close()

    # --- Femto ---
    fh = FEMTO_SFTP["host"]
    if str(fh or "").strip():
        ssh, sftp = _connect(
            fh, int(FEMTO_SFTP.get("port", 22)), FEMTO_SFTP["username"], FEMTO_SFTP["password"]
        )
        try:
            out["femto"] = _femto_remote_tree_sig(sftp, FEMTO_SFTP["remote_root"])
        finally:
            sftp.close()
            ssh.close()

    return out


def _hourly_keys() -> set[str]:
    return {k for k in (
        "hourly_huawei_cells",
        "hourly_huawei_groups",
        "hourly_nokia_cells",
        "hourly_nokia_groups",
        "metadata",
    )}


def _daily_keys() -> set[str]:
    return {k for k in (
        "daily_huawei_cells",
        "daily_huawei_groups",
        "daily_nokia_cells",
        "daily_nokia_groups",
    )}


PM_TARGET_BY_SIGNATURE: dict[str, tuple[str, str, str]] = {
    "hourly_huawei_cells": ("hourly", "huawei", "cells"),
    "hourly_huawei_groups": ("hourly", "huawei", "groups"),
    "hourly_nokia_cells": ("hourly", "nokia", "cells"),
    "hourly_nokia_groups": ("hourly", "nokia", "groups"),
    "daily_huawei_cells": ("daily", "huawei", "cells"),
    "daily_huawei_groups": ("daily", "huawei", "groups"),
    "daily_nokia_cells": ("daily", "nokia", "cells"),
    "daily_nokia_groups": ("daily", "nokia", "groups"),
}

METADATA_TARGET = ("snapshot", "metadata", "metadata")
_TABULAR_RAW_EXTS = (".csv", ".txt", ".tsv", ".xlsx", ".xls", ".xlsm")


def _target_label(target: tuple[str, str, str]) -> str:
    return "/".join(target)


def _expand_target(target: tuple[str, str, str]) -> set[tuple[str, str, str]]:
    scope, vendor, category = target
    if vendor == "metadata" or category != "all":
        return {target}
    return {(scope, vendor, "cells"), (scope, vendor, "groups")}


def _changed_targets(now: dict[str, str], prev: dict[str, str], *, first: bool, always_run: bool) -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for key, target in PM_TARGET_BY_SIGNATURE.items():
        if key not in now and key not in prev:
            continue
        if first or always_run or now.get(key) != prev.get(key):
            out.add(target)
    if first or always_run or now.get("metadata") != prev.get("metadata"):
        if now.get("metadata") or prev.get("metadata"):
            out.add(METADATA_TARGET)
    return out


def _collapse_targets(targets: set[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Merge cells+groups for the same vendor/scope into category=all."""
    metadata = sorted(t for t in targets if t[1] == "metadata")
    grouped: dict[tuple[str, str], set[str]] = {}
    for scope, vendor, category in targets:
        if vendor == "metadata":
            continue
        grouped.setdefault((scope, vendor), set()).add(category)

    out: list[tuple[str, str, str]] = []
    for (scope, vendor), categories in sorted(grouped.items()):
        if {"cells", "groups"}.issubset(categories):
            out.append((scope, vendor, "all"))
        else:
            out.extend((scope, vendor, category) for category in sorted(categories))
    return out + metadata


def _raw_file_count(folder: str) -> int:
    if not os.path.isdir(folder):
        return 0
    return sum(
        1
        for name in os.listdir(folder)
        if name.lower().endswith(_TABULAR_RAW_EXTS)
        and not name.startswith("~$")
        and os.path.isfile(os.path.join(folder, name))
    )


def _raw_count_for_target(target: tuple[str, str, str]) -> int:
    from pipeline.paths import iter_pm_raw_paths, raw_path

    scope, vendor, category = target
    if vendor == "metadata":
        return _raw_file_count(raw_path("metadata", "cells", "all", "snapshot"))

    domains = ("cells", "groups") if category == "all" else (category,)
    total = 0
    for domain in domains:
        for _tech, folder in iter_pm_raw_paths(vendor, domain, scope):
            total += _raw_file_count(folder)
    return total


def _pending_targets() -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for scope in ("hourly", "daily"):
        for vendor in ("huawei", "nokia"):
            for category in ("cells", "groups"):
                target = (scope, vendor, category)
                if _raw_count_for_target(target):
                    out.add(target)
    if _raw_count_for_target(METADATA_TARGET):
        out.add(METADATA_TARGET)
    return out


def _run_target(
    target: tuple[str, str, str],
    *,
    pull: bool,
    disable_time_filter: bool = False,
) -> int:
    from core.pipeline_run import (
        run_metadata_load_only,
        run_metadata_pull_load,
        run_pm_target_load_only,
        run_pm_target_pull_load,
    )

    scope, vendor, category = target
    if vendor == "metadata":
        return run_metadata_pull_load() if pull else run_metadata_load_only()
    if not pull:
        return run_pm_target_load_only(
            scope=scope,
            vendor=vendor,
            category=category,
            disable_time_filter=disable_time_filter,
        )
    return run_pm_target_pull_load(
        scope=scope,
        vendor=vendor,
        category=category,
        disable_time_filter=disable_time_filter,
    )


def _target_snapshot_keys(target: tuple[str, str, str]) -> list[str]:
    scope, vendor, category = target
    if vendor == "metadata":
        return []
    categories = ("cells", "groups") if category == "all" else (category,)
    return [f"{scope}_{vendor}_{cat}" for cat in categories]


def _target_ingest_advanced(before_all: dict, after_all: dict, target: tuple[str, str, str]) -> bool:
    from core.pipeline_ingest_verify import snapshot_advanced

    for key in _target_snapshot_keys(target):
        if snapshot_advanced(before_all.get(key) or {}, after_all.get(key) or {}):
            return True
    return False


def _target_needs_pull(target: tuple[str, str, str], remote_targets: set[tuple[str, str, str]]) -> bool:
    return bool(_expand_target(target) & remote_targets)

def run_cycle(state_path: Path, prev: dict[str, str]) -> dict[str, str]:
    from core.pipeline_ingest_verify import (
        capture_ingest_snapshot,
    )

    now = _probe_all()
    always_run = _env_bool("WATCH_ALWAYS_RUN", False)
    verify_db = _env_bool("WATCH_VERIFY_DB_INGEST", True)
    changed_femto = now.get("femto") != prev.get("femto") and (now.get("femto") or prev.get("femto"))

    first = len(prev) == 0
    if first or always_run:
        changed_femto = bool(now.get("femto") or prev.get("femto"))

    remote_targets = _changed_targets(now, prev, first=first, always_run=always_run)
    targets = set(remote_targets)

    # Staged raw files from a prior failed load — ingest the affected target only.
    pending = _pending_targets()
    for target in sorted(pending - targets):
        print(f"[watch] {_raw_count_for_target(target)} raw file(s) pending for {_target_label(target)}")
    targets |= pending
    targets_to_run = _collapse_targets(targets)

    snap_before = capture_ingest_snapshot() if verify_db else {}
    ran_targets: list[tuple[str, str, str]] = []
    rc = 0

    for target in targets_to_run:
        ran_targets.append(target)
        should_pull = _target_needs_pull(target, remote_targets)
        action = "pull+load" if should_pull else "load"
        print(f"[watch] target {action}: {_target_label(target)}")
        rc |= _run_target(target, pull=should_pull)

    if changed_femto or first:
        rc |= _run(os.path.join("pipeline", "pull_femto_raw.py"))
        rc |= _run(os.path.join("pipeline", "load_femto_pm_to_db.py"))

    if verify_db and rc == 0 and ran_targets:
        snap_after = capture_ingest_snapshot()
        for target in ran_targets:
            if target[1] == "metadata":
                continue
            raw_after = _raw_count_for_target(target)
            if raw_after <= 0 or _target_ingest_advanced(snap_before, snap_after, target):
                continue
            print(
                f"[watch] DB ingest did not advance for {_target_label(target)} "
                f"(raw files={raw_after}) — retry without time filter"
            )
            rc |= _run_target(target, pull=False, disable_time_filter=True)

    if rc != 0:
        print("[watch] a subprocess failed; state file not updated (will retry next cycle).")
        return prev

    if not (targets_to_run or changed_femto or first):
        print("[watch] no remote changes and no pending raw files; state not updated.")
        return prev

    to_save = dict(now)
    to_save["_saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    _save_state(state_path, to_save)
    return {k: v for k, v in now.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch remote paths and pull when files change.")
    parser.add_argument("--once", action="store_true", help="Run a single probe/pull cycle then exit.")
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help=(
            "Override poll interval in seconds (default: WATCH_POLL_INTERVAL_SEC env or "
            f"{DEFAULT_WATCH_POLL_INTERVAL_SEC} = 30 minutes)."
        ),
    )
    args = parser.parse_args()

    interval = args.interval if args.interval is not None else _env_int(
        "WATCH_POLL_INTERVAL_SEC", DEFAULT_WATCH_POLL_INTERVAL_SEC
    )
    state_path = Path(os.getenv("WATCH_STATE_FILE") or DEFAULT_STATE)
    always_run = _env_bool("WATCH_ALWAYS_RUN", False)

    print(f"[watch] state={state_path} interval={interval}s once={args.once} always_run={always_run}")

    prev = {k: v for k, v in _load_state(state_path).items() if not k.startswith("_")}

    while True:
        try:
            print(f"[watch] probe at {time.strftime('%H:%M:%S')}")
            prev = run_cycle(state_path, prev)
        except Exception as exc:
            print(f"[watch] cycle error: {exc}", file=sys.stderr)

        if args.once:
            break
        time.sleep(max(30, interval))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
