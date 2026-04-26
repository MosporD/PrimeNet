"""
Step 1 pipeline: pull latest metadata snapshot CSVs.

- Connect to metadata server.
- Enter newest folder under configured root.
- Download the latest 5 CSV files (by mtime) to raw/metadata/cells.
"""

import os
import stat

import paramiko

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import METADATA_SERVER, PROJECT_ROOT


def _open_sftp():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=METADATA_SERVER["host"],
        port=METADATA_SERVER.get("port", 22),
        username=METADATA_SERVER.get("username", ""),
        password=METADATA_SERVER.get("password", ""),
        timeout=30,
    )
    return ssh, ssh.open_sftp()


def _latest_snapshot_dir(sftp, root_dir: str) -> str | None:
    entries = sftp.listdir_attr(root_dir)
    subdirs = [e for e in entries if stat.S_ISDIR(e.st_mode)]
    if not subdirs:
        return None
    subdirs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
    return f"{root_dir.rstrip('/')}/{subdirs[0].filename}"


def main() -> int:
    out_dir = os.path.join(PROJECT_ROOT, "raw", "metadata", "cells")
    os.makedirs(out_dir, exist_ok=True)

    ssh, sftp = _open_sftp()
    try:
        root_dir = METADATA_SERVER.get("root_dir", "/")
        latest_dir = _latest_snapshot_dir(sftp, root_dir)
        if not latest_dir:
            print(f"[metadata] no snapshot folders found under: {root_dir}")
            return 1

        entries = sftp.listdir_attr(latest_dir)
        csv_files = [
            e for e in entries
            if not stat.S_ISDIR(e.st_mode) and e.filename.lower().endswith(".csv")
        ]
        if not csv_files:
            print(f"[metadata] no CSV files found in latest folder: {latest_dir}")
            return 1

        csv_files.sort(key=lambda e: e.st_mtime or 0, reverse=True)
        chosen = csv_files[:5]

        for e in chosen:
            remote_path = f"{latest_dir.rstrip('/')}/{e.filename}"
            local_name = e.filename
            local_path = os.path.join(out_dir, local_name)
            sftp.get(remote_path, local_path)
            print(f"[metadata] downloaded: {remote_path} -> {local_path}")

        print(f"[metadata] completed: downloaded {len(chosen)} file(s) from {latest_dir}")
        return 0
    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
