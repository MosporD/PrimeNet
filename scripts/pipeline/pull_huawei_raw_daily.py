"""
Step 1 pipeline: pull latest Huawei DAILY raw files.

- Cells file  -> raw/daily/huawei/cells
- Groups file -> raw/daily/huawei/groups
"""

import os
import stat
import zipfile
import argparse
from concurrent.futures import ThreadPoolExecutor

import paramiko
import pandas as pd

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from sync_config import HUAWEI_PM_DAILY_SERVER, HUAWEI_GROUPS_DAILY_SERVER, PROJECT_ROOT
from pipeline.paths import raw_path


ALLOWED_EXTS = (".xlsx", ".xls", ".xlsm", ".csv", ".zip")


def _open_sftp(host: str, port: int, username: str, password: str):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=host, port=port, username=username, password=password, timeout=30)
    return ssh, ssh.open_sftp()


def _build_search_dirs(sftp, remote_dir: str, descend: bool) -> list[str]:
    if not descend:
        return [remote_dir]
    search_dirs = [remote_dir]
    try:
        entries = sftp.listdir_attr(remote_dir)
    except OSError:
        return search_dirs
    subdirs = [e for e in entries if stat.S_ISDIR(e.st_mode)]
    subdirs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
    for sd in subdirs:
        search_dirs.append(f"{remote_dir.rstrip('/')}/{sd.filename}")
    return search_dirs


def _latest_file_in_remote_dir(sftp, remote_dir: str, descend: bool):
    best = None
    for d in _build_search_dirs(sftp, remote_dir, descend):
        try:
            entries = sftp.listdir_attr(d)
        except OSError:
            continue
        for e in entries:
            if stat.S_ISDIR(e.st_mode):
                continue
            if not e.filename.lower().endswith(ALLOWED_EXTS):
                continue
            mtime = float(e.st_mtime or 0)
            full = f"{d.rstrip('/')}/{e.filename}"
            if best is None or mtime > best[0]:
                best = (mtime, full, e.filename)
    return best


def _download_latest(server_cfg: dict, remote_dir: str, local_dir: str, label: str):
    os.makedirs(local_dir, exist_ok=True)
    ssh, sftp = _open_sftp(
        server_cfg["host"],
        server_cfg.get("port", 22),
        server_cfg.get("username", ""),
        server_cfg.get("password", ""),
    )
    try:
        best = _latest_file_in_remote_dir(
            sftp,
            remote_dir,
            bool(server_cfg.get("descend_into_newest_subdir", False)),
        )
        if not best:
            print(f"[daily/{label}] no files found under: {remote_dir}")
            return None
        _, remote_path, filename = best
        local_path = os.path.join(local_dir, filename)
        sftp.get(remote_path, local_path)
        print(f"[daily/{label}] downloaded: {remote_path} -> {local_path}")
        return local_path
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
                print(f"[daily/zip] no extractable tabular members in {path}")
                return
            for m in members:
                target_name = os.path.basename(m)
                if not target_name:
                    continue
                target_path = os.path.join(out_dir, target_name)
                try:
                    with zf.open(m) as src, open(target_path, "wb") as dst:
                        dst.write(src.read())
                except PermissionError:
                    root, ext = os.path.splitext(target_name)
                    target_path = os.path.join(out_dir, f"{root}__new{ext}")
                    with zf.open(m) as src, open(target_path, "wb") as dst:
                        dst.write(src.read())
                    print(f"[daily/zip] target locked, wrote fallback file: {target_path}")
                extracted += 1
        os.remove(path)
        print(f"[daily/zip] extracted {extracted} file(s) and removed archive: {path}")
    except zipfile.BadZipFile:
        print(f"[daily/zip] skip invalid zip archive: {path}")


def _safe_sheet_name(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name or "").strip()).strip("_") or "sheet"


def _convert_excel_file_to_csv(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    if not path.lower().endswith((".xlsx", ".xls", ".xlsm")):
        return 0
    try:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str, engine=None)
    except Exception as e:
        print(f"[daily/csv-normalize] failed reading workbook {path}: {e}")
        return 0

    base = os.path.splitext(path)[0]
    written = 0
    for sheet_name, df in (sheets or {}).items():
        if len(sheets) == 1:
            out_path = f"{base}.csv"
        else:
            out_path = f"{base}__{_safe_sheet_name(sheet_name)}.csv"
        try:
            (df if df is not None else pd.DataFrame()).to_csv(out_path, index=False, encoding="utf-8")
            written += 1
        except Exception as e:
            print(f"[daily/csv-normalize] failed writing CSV {out_path}: {e}")
    if written:
        try:
            os.remove(path)
        except OSError as e:
            print(f"[daily/csv-normalize] kept source workbook (remove failed): {path} ({e})")
        print(f"[daily/csv-normalize] converted workbook to {written} csv file(s): {path}")
    return written


def _normalize_folder_to_csv(folder: str, label: str) -> int:
    if not os.path.isdir(folder):
        return 0
    converted = 0
    for name in os.listdir(folder):
        fp = os.path.join(folder, name)
        if not os.path.isfile(fp):
            continue
        converted += _convert_excel_file_to_csv(fp)
    if converted:
        print(f"[daily/{label}] csv normalization converted {converted} workbook sheet(s)")
    return converted


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull latest Huawei daily raw files")
    parser.add_argument("--category", choices=("all", "cells", "groups"), default="all")
    args = parser.parse_args()

    pull_cells = args.category in ("all", "cells")
    pull_groups = args.category in ("all", "groups")
    cells_dir = raw_path("huawei", "cells", "all", "daily")
    groups_dir = raw_path("huawei", "groups", "all", "daily")

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_cells = (
            pool.submit(
                _download_latest,
                HUAWEI_PM_DAILY_SERVER,
                HUAWEI_PM_DAILY_SERVER["remote_dir"],
                cells_dir,
                "cells",
            )
            if pull_cells
            else None
        )
        fut_groups = (
            pool.submit(
                _download_latest,
                HUAWEI_GROUPS_DAILY_SERVER,
                HUAWEI_GROUPS_DAILY_SERVER["remote_dir"],
                groups_dir,
                "groups",
            )
            if pull_groups
            else None
        )
        cells_path = fut_cells.result() if fut_cells else None
        groups_path = fut_groups.result() if fut_groups else None

    if pull_cells:
        _extract_zip_csvs(cells_path)
        _normalize_folder_to_csv(cells_dir, "cells")
    if pull_groups:
        _extract_zip_csvs(groups_path)
        _normalize_folder_to_csv(groups_dir, "groups")
    if not cells_path and not groups_path:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
