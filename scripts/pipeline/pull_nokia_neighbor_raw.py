"""
Pull latest Nokia neighbor export per RAT (2G / 3G / 4G) from NetAct SFTP.

Files land under: raw/nokia/neighbor/<2G|3G|4G>/
Same host/credentials as Nokia PM; paths from sync_config.NOKIA_NEIGHBOR_SERVER.
"""

from __future__ import annotations

import os
import stat
import zipfile

import paramiko
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from sync_config import NOKIA_NEIGHBOR_SERVER, PROJECT_ROOT
from pipeline.paths import raw_path

ALLOWED_EXTS = (".xlsx", ".xls", ".xlsm", ".csv", ".zip")


def _clear_neighbor_rat_folders(base: str) -> None:
    """Remove previous neighbor exports so each pull matches SFTP only."""
    for tech in ("2G", "3G", "4G"):
        d = os.path.join(base, tech)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            low = name.lower()
            if low.endswith(ALLOWED_EXTS):
                try:
                    os.remove(os.path.join(d, name))
                except OSError as ex:
                    print(f"[neighbor/nokia] could not remove {d}/{name}: {ex}")


def _open_sftp(server_cfg: dict):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=server_cfg["host"],
        port=server_cfg.get("port", 22),
        username=server_cfg.get("username", ""),
        password=server_cfg.get("password", ""),
        timeout=30,
    )
    return ssh, ssh.open_sftp()


def _candidate_dirs_for_remote(sftp, remote_dir: str, descend: bool) -> list[str]:
    dirs = [remote_dir]
    if not descend:
        return dirs
    try:
        entries = sftp.listdir_attr(remote_dir)
    except OSError:
        return dirs
    subdirs = [e for e in entries if stat.S_ISDIR(e.st_mode)]
    subdirs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
    for sd in subdirs:
        dirs.append(f"{remote_dir.rstrip('/')}/{sd.filename}")
    return dirs


def _latest_for_dir(sftp, remote_dir: str, descend: bool):
    best = None
    for scan_dir in _candidate_dirs_for_remote(sftp, remote_dir, descend):
        try:
            entries = sftp.listdir_attr(scan_dir)
        except OSError:
            continue
        for e in entries:
            if stat.S_ISDIR(e.st_mode):
                continue
            if not e.filename.lower().endswith(ALLOWED_EXTS):
                continue
            mtime = float(e.st_mtime or 0)
            full_path = f"{scan_dir.rstrip('/')}/{e.filename}"
            if best is None or mtime > best[0]:
                best = (mtime, full_path, e.filename, remote_dir)
    return best


def _extract_zip_csvs(path: str):
    if not path or not path.lower().endswith(".zip") or not os.path.isfile(path):
        return
    out_dir = os.path.dirname(path)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            members = [m for m in zf.namelist() if not m.endswith("/") and m.lower().endswith(".csv")]
            if not members:
                members = [
                    m
                    for m in zf.namelist()
                    if not m.endswith("/") and m.lower().endswith((".csv", ".xlsx", ".xls", ".xlsm", ".txt", ".tsv"))
                ]
            if not members:
                print(f"[neighbor/zip] no extractable tabular members in {path}")
                return
            for m in members:
                target_name = os.path.basename(m)
                if not target_name:
                    continue
                with zf.open(m) as src, open(os.path.join(out_dir, target_name), "wb") as dst:
                    dst.write(src.read())
        os.remove(path)
        print(f"[neighbor/zip] extracted archive: {path}")
    except zipfile.BadZipFile:
        print(f"[neighbor/zip] skip invalid zip: {path}")


def main() -> int:
    cfg = NOKIA_NEIGHBOR_SERVER
    if not str(cfg.get("host") or "").strip():
        print("[neighbor] NOKIA_NEIGHBOR_SERVER host not configured.")
        return 1

    base = raw_path("nokia", "neighbor", "all", "hourly")
    _clear_neighbor_rat_folders(base)

    dirs_map = dict(cfg.get("dirs") or {})
    if not dirs_map:
        print("[neighbor] no dirs in NOKIA_NEIGHBOR_SERVER")
        return 1

    descend = bool(cfg.get("descend_into_newest_subdir", False))
    ssh, sftp = _open_sftp(cfg)
    downloaded: dict[str, str | None] = {}
    try:
        for tech, remote_dir in dirs_map.items():
            local_dir = os.path.join(base, tech)
            os.makedirs(local_dir, exist_ok=True)
            best = _latest_for_dir(sftp, remote_dir, descend)
            if not best:
                print(f"[neighbor/{tech}] no file found in: {remote_dir}")
                downloaded[tech] = None
                continue
            _, remote_path, filename, src = best
            local_path = os.path.join(local_dir, filename)
            sftp.get(remote_path, local_path)
            print(f"[neighbor/{tech}] downloaded from {src}: {remote_path} -> {local_path}")
            downloaded[tech] = local_path
    finally:
        sftp.close()
        ssh.close()

    for p in downloaded.values():
        if p:
            _extract_zip_csvs(p)

    if not any(downloaded.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
