"""
Step 1 pipeline: pull latest Nokia raw files.

- Cells: always pull latest per technology (2G/3G/4G/5G)  -> raw/nokia/cells
- Groups: always pull latest per technology (2G/3G/4G/5G) -> raw/nokia/groups
"""

import os
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor

import paramiko

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import NOKIA_PM_SERVER, NOKIA_GROUPS_SERVER, PROJECT_ROOT


ALLOWED_EXTS = (".xlsx", ".xls", ".xlsm", ".csv", ".zip")


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
    best = None  # (mtime, full_path, filename, source_dir)
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


def _download_latest_per_tech(server_cfg: dict, tech_dirs: dict[str, str], local_dir: str, label: str):
    os.makedirs(local_dir, exist_ok=True)
    ssh, sftp = _open_sftp(server_cfg)
    try:
        descend = bool(server_cfg.get("descend_into_newest_subdir", False))
        downloaded = {}
        for tech, remote_dir in tech_dirs.items():
            best = _latest_for_dir(sftp, remote_dir, descend)
            if not best:
                print(f"[{label}/{tech}] no file found in: {remote_dir}")
                downloaded[tech] = None
                continue
            _, remote_path, filename, src = best
            local_name = filename
            local_path = os.path.join(local_dir, local_name)
            sftp.get(remote_path, local_path)
            print(f"[{label}/{tech}] downloaded from {src}: {remote_path} -> {local_path}")
            downloaded[tech] = local_path
        return downloaded
    finally:
        sftp.close()
        ssh.close()


def _extract_zip_csvs(path: str):
    if not path or not path.lower().endswith(".zip") or not os.path.isfile(path):
        return
    out_dir = os.path.dirname(path)
    extracted = 0
    try:
        with zipfile.ZipFile(path, "r") as zf:
            members = [m for m in zf.namelist() if not m.endswith("/") and m.lower().endswith(".csv")]
            if not members:
                members = [
                    m for m in zf.namelist()
                    if not m.endswith("/") and m.lower().endswith((".csv", ".xlsx", ".xls", ".xlsm", ".txt", ".tsv"))
                ]
            if not members:
                print(f"[zip] no extractable tabular members in {path}")
                return
            for m in members:
                target_name = os.path.basename(m)
                if not target_name:
                    continue
                with zf.open(m) as src, open(os.path.join(out_dir, target_name), "wb") as dst:
                    dst.write(src.read())
                extracted += 1
        os.remove(path)
        print(f"[zip] extracted {extracted} file(s) and removed archive: {path}")
    except zipfile.BadZipFile:
        print(f"[zip] skip invalid zip archive: {path}")


def main() -> int:
    raw_root = os.path.join(PROJECT_ROOT, "raw", "nokia")
    cells_dir = os.path.join(raw_root, "cells")
    groups_dir = os.path.join(raw_root, "groups")

    cells_remote_map = dict(NOKIA_PM_SERVER.get("dirs") or {})
    groups_remote_map = dict(NOKIA_GROUPS_SERVER.get("dirs") or {})

    # Per-vendor PM vs groups are independent; overlap the two multi-tech SFTP sessions.
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_cells = pool.submit(
            _download_latest_per_tech,
            NOKIA_PM_SERVER,
            cells_remote_map,
            cells_dir,
            "cells",
        )
        fut_groups = pool.submit(
            _download_latest_per_tech,
            NOKIA_GROUPS_SERVER,
            groups_remote_map,
            groups_dir,
            "groups",
        )
        cells_downloads = fut_cells.result()
        groups_downloads = fut_groups.result()
    for p in cells_downloads.values():
        _extract_zip_csvs(p)
    for p in groups_downloads.values():
        _extract_zip_csvs(p)
    if not any(cells_downloads.values()) and not any(groups_downloads.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
