"""
Step 1 pipeline: pull latest Huawei raw files.

- Cells file  -> raw/huawei/cells
- Groups file -> raw/huawei/groups
"""

import os
import stat
import time
import zipfile
import shutil
import argparse
from concurrent.futures import ThreadPoolExecutor

import paramiko
import pandas as pd

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from sync_config import (
    HUAWEI_PM_SERVER,
    HUAWEI_GROUPS_SERVER,
    RAW_PULL_AUTO_LOAD,
    RAW_PULL_CLEAR_BEFORE,
    RAW_PULL_PRUNE_AFTER,
    RAW_KEEP_FILES_PER_TECH,
)
from pipeline.paths import iter_pm_raw_paths, raw_path
from core.raw_pm_files import (
    clear_tabular_files,
    prune_stale_pm_files,
    relocate_legacy_all_folder,
)


ALLOWED_EXTS = (".xlsx", ".xls", ".xlsm", ".csv", ".zip")


def _safe_remove(path: str, *, label: str = "file") -> bool:
    """Best-effort delete; retry on Windows when another sync still has the file open."""
    for attempt in range(6):
        try:
            os.remove(path)
            return True
        except PermissionError as exc:
            if attempt < 5:
                time.sleep(0.25 * (attempt + 1))
                continue
            print(f"[zip] extraction ok; could not remove {label} (locked): {path} ({exc})")
            return False
        except OSError as exc:
            print(f"[zip] could not remove {label}: {path} ({exc})")
            return False
    return False


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
    best = None  # tuple(mtime, full_path, filename)
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
            print(f"[{label}] no files found under: {remote_dir}")
            return None
        _, remote_path, filename = best
        local_name = filename
        local_path = os.path.join(local_dir, local_name)
        sftp.get(remote_path, local_path)
        print(f"[{label}] downloaded: {remote_path} -> {local_path}")
        return local_path
    finally:
        sftp.close()
        ssh.close()


def _extract_zip_csvs(path: str):
    if not path or not path.lower().endswith(".zip") or not os.path.isfile(path):
        return
    out_dir = os.path.dirname(path)
    extracted = 0
    skipped = 0
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
                target_path = os.path.join(out_dir, target_name)
                try:
                    with zf.open(m) as src, open(target_path, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                except PermissionError:
                    # If an old file is locked by another process, keep going with a fallback name.
                    root, ext = os.path.splitext(target_name)
                    target_path = os.path.join(out_dir, f"{root}__new{ext}")
                    with zf.open(m) as src, open(target_path, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                    print(f"[zip] target locked, wrote fallback file: {target_path}")
                except (EOFError, OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as e:
                    skipped += 1
                    print(f"[zip] skipped corrupt member '{m}' in {path}: {e}")
                    try:
                        if os.path.isfile(target_path):
                            os.remove(target_path)
                    except OSError:
                        pass
                    continue
                extracted += 1
        if extracted > 0:
            removed = _safe_remove(path, label="archive")
            msg = f"[zip] extracted {extracted} file(s)"
            if skipped:
                msg += f", skipped {skipped} corrupt member(s)"
            if removed:
                print(f"{msg} and removed archive: {path}")
            else:
                print(f"{msg}; archive kept (remove failed): {path}")
        else:
            print(f"[zip] no valid members extracted from archive (skipped={skipped}): {path}")
    except zipfile.BadZipFile:
        print(f"[zip] skip invalid zip archive: {path}")


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
        print(f"[csv-normalize] failed reading workbook {path}: {e}")
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
            print(f"[csv-normalize] failed writing CSV {out_path}: {e}")
    if written:
        if not _safe_remove(path, label="workbook"):
            print(f"[csv-normalize] kept source workbook (remove failed): {path}")
        print(f"[csv-normalize] converted workbook to {written} csv file(s): {path}")
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
        print(f"[{label}] csv normalization converted {converted} workbook sheet(s)")
    return converted


def _prepare_raw_folder(folder: str, label: str) -> None:
    if RAW_PULL_CLEAR_BEFORE:
        removed = clear_tabular_files(folder)
        if removed:
            print(f"[{label}] cleared {removed} old raw file(s) before pull: {folder}")


def _finalize_raw_folder(folder: str, label: str) -> None:
    if RAW_PULL_PRUNE_AFTER:
        removed = prune_stale_pm_files(folder, keep_per_technology=RAW_KEEP_FILES_PER_TECH)
        if removed:
            print(f"[{label}] pruned {removed} older raw file(s) after pull: {folder}")


def _prepare_vendor_domain(vendor: str, domain: str, scope: str) -> None:
    n = relocate_legacy_all_folder(vendor, domain, scope)
    if n:
        print(f"[{domain}] relocated {n} file(s) from legacy .../all/... to per-RAT folders")
    for _tech, folder in iter_pm_raw_paths(vendor, domain, scope):
        _prepare_raw_folder(folder, f"{domain}/{_tech}")


def _finalize_vendor_domain(vendor: str, domain: str, scope: str) -> None:
    for _tech, folder in iter_pm_raw_paths(vendor, domain, scope):
        _finalize_raw_folder(folder, f"{domain}/{_tech}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull latest Huawei hourly raw files")
    parser.add_argument("--category", choices=("all", "cells", "groups"), default="all")
    args = parser.parse_args()

    scope = "hourly"
    vendor = "huawei"
    pull_cells = args.category in ("all", "cells")
    pull_groups = args.category in ("all", "groups")
    # Huawei exports land in a shared SFTP folder; pull to legacy ``all/`` then split by RAT.
    cells_staging = raw_path(vendor, "cells", "all", scope)
    groups_staging = raw_path(vendor, "groups", "all", scope)

    if pull_cells:
        _prepare_vendor_domain(vendor, "cells", scope)
        _prepare_raw_folder(cells_staging, "cells/staging")
    if pull_groups:
        _prepare_vendor_domain(vendor, "groups", scope)
        _prepare_raw_folder(groups_staging, "groups/staging")

    # Cells and groups are independent; run both SFTP pulls concurrently.
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_cells = (
            pool.submit(
                _download_latest,
                HUAWEI_PM_SERVER,
                HUAWEI_PM_SERVER["remote_dir"],
                cells_staging,
                "cells",
            )
            if pull_cells
            else None
        )
        fut_groups = (
            pool.submit(
                _download_latest,
                HUAWEI_GROUPS_SERVER,
                HUAWEI_GROUPS_SERVER["remote_dir"],
                groups_staging,
                "groups",
            )
            if pull_groups
            else None
        )
        cells_path = fut_cells.result() if fut_cells else None
        groups_path = fut_groups.result() if fut_groups else None
    if pull_cells:
        _extract_zip_csvs(cells_path)
    if pull_groups:
        _extract_zip_csvs(groups_path)
    # Keep raw Huawei inputs uniform for downstream processing: only CSV files.
    if pull_cells:
        _normalize_folder_to_csv(cells_staging, "cells")
    if pull_groups:
        _normalize_folder_to_csv(groups_staging, "groups")

    n_cells = relocate_legacy_all_folder(vendor, "cells", scope) if pull_cells else 0
    n_groups = relocate_legacy_all_folder(vendor, "groups", scope) if pull_groups else 0
    if n_cells or n_groups:
        print(f"[huawei] split staging exports: cells={n_cells} groups={n_groups} file(s)")

    if pull_cells:
        _finalize_vendor_domain(vendor, "cells", scope)
    if pull_groups:
        _finalize_vendor_domain(vendor, "groups", scope)

    if not cells_path and not groups_path:
        return 1

    if RAW_PULL_AUTO_LOAD:
        from core.pipeline_load import run_pm_load

        load_rc = run_pm_load(scope="hourly", vendor="huawei", category=args.category)
        if load_rc != 0:
            print(f"[huawei] load after pull failed with code {load_rc}")
            return load_rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
