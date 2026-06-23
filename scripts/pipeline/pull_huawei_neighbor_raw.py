"""
Pull latest Huawei neighbor bundle from OMC SFTP: one .zip in a single remote folder
containing 2G / 3G / 4G tabular exports. Files are routed into:

  raw/huawei/neighbor/2G/
  raw/huawei/neighbor/3G/
  raw/huawei/neighbor/4G/

Remote path: sync_config.HUAWEI_NEIGHBOR_SERVER['zip_remote_dir'] (env HUAWEI_NEIGHBOR_ZIP_DIR).
Same credentials as Huawei PM.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile

import paramiko
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from sync_config import HUAWEI_NEIGHBOR_SERVER, PROJECT_ROOT
from pipeline.paths import raw_path

ALLOWED_ZIP = ".zip"
_TABULAR_SUFFIX = (".csv", ".xlsx", ".xls", ".xlsm", ".txt", ".tsv")


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


def _latest_zip_in_tree(sftp, remote_root: str, descend: bool):
    """Newest .zip under remote_root (optionally newest dated subfolder first)."""
    best = None
    for scan_dir in _candidate_dirs_for_remote(sftp, remote_root, descend):
        try:
            entries = sftp.listdir_attr(scan_dir)
        except OSError:
            continue
        for e in entries:
            if stat.S_ISDIR(e.st_mode):
                continue
            if not e.filename.lower().endswith(ALLOWED_ZIP):
                continue
            mtime = float(e.st_mtime or 0)
            full_path = f"{scan_dir.rstrip('/')}/{e.filename}"
            if best is None or mtime > best[0]:
                best = (mtime, full_path, e.filename, remote_root)
    return best


def _clear_neighbor_rat_folders(base: str) -> None:
    for tech in ("2G", "3G", "4G"):
        d = os.path.join(base, tech)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            low = name.lower()
            if low.endswith(_TABULAR_SUFFIX) or low.endswith(ALLOWED_ZIP):
                try:
                    os.remove(os.path.join(d, name))
                except OSError as ex:
                    print(f"[neighbor/huawei] could not remove {d}/{name}: {ex}")
    staging = os.path.join(base, "_staging")
    if os.path.isdir(staging):
        for name in os.listdir(staging):
            low = name.lower()
            if low.endswith(ALLOWED_ZIP):
                try:
                    os.remove(os.path.join(staging, name))
                except OSError as ex:
                    print(f"[neighbor/huawei] could not remove {staging}/{name}: {ex}")


def _rat_from_zip_member(relative_path: str) -> str | None:
    """Map zip entry path/name to 2G / 3G / 4G using common PRS / folder naming."""
    s = relative_path.replace("\\", "/").lower()
    base = os.path.basename(s)

    def has_any(keys: tuple[str, ...]) -> bool:
        return any(k in s or k in base for k in keys)

    if has_any(("5g", "nr_", "/nr/", "gnodeb", "gnb")):
        return None
    if has_any(("4g", "/4g/", "_4g_", "lte", "eutran", "lncel", "enodeb", "enb_", "_enb")):
        return "4G"
    if has_any(("3g", "/3g/", "_3g_", "umts", "wcdma", "utran", "rnc", "nodeb")):
        return "3G"
    if has_any(("2g", "/2g/", "_2g_", "gsm", "geran", "bsc", "gprs")):
        return "2G"

    m = re.match(r"^(2g|3g|4g)[^a-z0-9]", base, re.I)
    if m:
        return m.group(1).upper()
    return None


def _zip_tabular_members(zf: zipfile.ZipFile) -> list[str]:
    names = []
    for m in zf.namelist():
        if m.endswith("/"):
            continue
        low = m.lower()
        if low.endswith(_TABULAR_SUFFIX):
            names.append(m)
    return names


def _extract_bundle_to_rat_folders(zip_path: str, base: str) -> int:
    """
    Extract tabular members from zip into raw/huawei/neighbor/<2G|3G|4G>/.
    Returns number of files written.
    """
    written = 0
    pending: list[tuple[str, str]] = []  # (member, target_basename)

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = _zip_tabular_members(zf)
        if not members:
            print(f"[neighbor/zip] no tabular members in {zip_path}")
            return 0

        tmp = tempfile.mkdtemp(prefix="huawei_neighbor_zip_")
        try:
            for i, m in enumerate(members):
                rat = _rat_from_zip_member(m)
                base_name = os.path.basename(m) or "export"
                if not base_name or base_name.endswith("/"):
                    continue
                safe_name = base_name.replace("\\", "_").replace("/", "_")
                tmp_path = os.path.join(tmp, f"{i:02d}_{safe_name}")
                with zf.open(m, "r") as src, open(tmp_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                pending.append((rat, safe_name, tmp_path))

            unrouted_triples = [(bn, tp) for rat, bn, tp in pending if rat is None]
            routed = [(rat, bn, tp) for rat, bn, tp in pending if rat is not None]

            if unrouted_triples and len(unrouted_triples) == 3 and not routed:
                print("[neighbor/zip] could not infer RAT from names; assigning 3 files to 2G, 3G, 4G by sort order")
                for tech, (bn, tp) in zip(
                    ("2G", "3G", "4G"),
                    sorted(unrouted_triples, key=lambda x: x[0].lower()),
                ):
                    dest_dir = os.path.join(base, tech)
                    os.makedirs(dest_dir, exist_ok=True)
                    dest = os.path.join(dest_dir, bn)
                    shutil.move(tp, dest)
                    written += 1
                    print(f"[neighbor/huawei/{tech}] <- zip member -> {bn}")
            else:
                if unrouted_triples:
                    print(
                        f"[neighbor/zip] warning: {len(unrouted_triples)} file(s) not routed "
                        f"(no RAT in name): {[b for b, _ in unrouted_triples]}"
                    )
                for rat, bn, tp in routed:
                    dest_dir = os.path.join(base, rat)
                    os.makedirs(dest_dir, exist_ok=True)
                    dest = os.path.join(dest_dir, bn)
                    shutil.move(tp, dest)
                    written += 1
                    print(f"[neighbor/huawei/{rat}] <- {bn}")
                for _bn, tp in unrouted_triples:
                    try:
                        os.remove(tp)
                    except OSError:
                        pass
        finally:
            try:
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass

    if written > 0:
        try:
            os.remove(zip_path)
        except OSError as ex:
            print(f"[neighbor/zip] could not remove archive {zip_path}: {ex}")
        else:
            print(f"[neighbor/zip] removed archive after extract: {zip_path}")
    else:
        print(f"[neighbor/zip] leaving archive in place (nothing written): {zip_path}")

    return written


def main() -> int:
    cfg = HUAWEI_NEIGHBOR_SERVER
    if not str(cfg.get("host") or "").strip():
        print("[neighbor] HUAWEI_NEIGHBOR_SERVER host not configured.")
        return 1

    remote_root = str(cfg.get("zip_remote_dir") or "").strip()
    if not remote_root:
        print("[neighbor] HUAWEI_NEIGHBOR_SERVER zip_remote_dir not configured.")
        return 1

    base = raw_path("huawei", "neighbor", "all", "hourly")
    _clear_neighbor_rat_folders(base)

    descend = bool(cfg.get("descend_into_newest_subdir", False))
    ssh, sftp = _open_sftp(cfg)
    try:
        best = _latest_zip_in_tree(sftp, remote_root, descend)
        if not best:
            print(f"[neighbor/huawei] no .zip found under: {remote_root}")
            return 1
        _, remote_path, filename, src = best
        staging = os.path.join(base, "_staging")
        os.makedirs(staging, exist_ok=True)
        local_zip = os.path.join(staging, filename)
        sftp.get(remote_path, local_zip)
        print(f"[neighbor/huawei] downloaded from {src}: {remote_path} -> {local_zip}")
    finally:
        sftp.close()
        ssh.close()

    n = _extract_bundle_to_rat_folders(local_zip, base)
    if n <= 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
