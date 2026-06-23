"""
Pull all Femto files from SFTP path into raw/femto.
"""

from __future__ import annotations

import os
from stat import S_ISDIR

import paramiko


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_ROOT = os.path.join(PROJECT_ROOT, "raw", "femto")

SFTP_CFG = {
    "host": "10.253.92.68",
    "port": 22,
    "username": "ftpuser",
    "password": "SmallCells@@25",
    "remote_root": "/femto/stats/",
}


def _connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=SFTP_CFG["host"],
        port=SFTP_CFG["port"],
        username=SFTP_CFG["username"],
        password=SFTP_CFG["password"],
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    return ssh, ssh.open_sftp()


def _pull_tree(sftp, remote_dir: str, local_dir: str) -> tuple[int, int]:
    os.makedirs(local_dir, exist_ok=True)
    file_count = 0
    dir_count = 0

    for entry in sftp.listdir_attr(remote_dir):
        remote_path = f"{remote_dir.rstrip('/')}/{entry.filename}"
        local_path = os.path.join(local_dir, entry.filename)
        if S_ISDIR(entry.st_mode):
            d_files, d_dirs = _pull_tree(sftp, remote_path, local_path)
            file_count += d_files
            dir_count += d_dirs + 1
            continue
        remote_size = int(getattr(entry, "st_size", 0) or 0)
        if remote_size == 0:
            print(f"[skip] empty remote file: {remote_path}")
            continue
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        sftp.get(remote_path, local_path)
        local_size = os.path.getsize(local_path) if os.path.isfile(local_path) else 0
        if local_size == 0:
            print(f"[warn] downloaded empty file, removing: {local_path}")
            try:
                os.remove(local_path)
            except OSError:
                pass
            continue
        file_count += 1
        print(f"[downloaded] {remote_path} -> {local_path}")

    return file_count, dir_count


def main() -> int:
    os.makedirs(LOCAL_ROOT, exist_ok=True)
    ssh = None
    sftp = None
    try:
        ssh, sftp = _connect()
        files, dirs = _pull_tree(sftp, SFTP_CFG["remote_root"], LOCAL_ROOT)
        print(f"[done] files={files}, dirs={dirs}, local_root={LOCAL_ROOT}")
        return 0
    except Exception as exc:
        print(f"[error] femto pull failed: {exc}")
        return 1
    finally:
        if sftp:
            sftp.close()
        if ssh:
            ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())

