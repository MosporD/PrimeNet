"""
SFTP Client
===========
Handles connecting to SFTP servers and downloading files.

Key methods
-----------
download_latest_xlsx(remote_dir, prefix)
    List all .xlsx/.xls files in remote_dir, download the newest by mtime.

download_latest_subdir_files(root_dir, tech_filename_map, prefix)
    List subdirectories in root_dir, enter the newest one, then download
    one file per technology according to tech_filename_map.
    Used by the Metadata server which stores dated snapshot folders.
"""

import os
import stat
import logging
import paramiko
from datetime import datetime

logger = logging.getLogger(__name__)

EXCEL_EXTS = ('.xlsx', '.xls')


class SFTPClient:
    def __init__(self, host, port, username, password, local_dir):
        self.host      = host
        self.port      = port
        self.username  = username
        self.password  = password
        self.local_dir = local_dir
        os.makedirs(local_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open(self):
        """Return (ssh, sftp) — caller must close both."""
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=30
        )
        return ssh, ssh.open_sftp()

    def _download(self, sftp, remote_path, local_filename):
        local_path = os.path.join(self.local_dir, local_filename)
        sftp.get(remote_path, local_path)
        logger.info(f'Downloaded {remote_path} → {local_path}')
        return local_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download_latest_xlsx(self, remote_dir, prefix=''):
        """
        List XLSX files in remote_dir, download the one with the newest
        modification time. Returns local path, or None on failure.
        """
        ssh, sftp = None, None
        try:
            ssh, sftp = self._open()
            entries = sftp.listdir_attr(remote_dir)
            xlsx = [
                e for e in entries
                if not stat.S_ISDIR(e.st_mode)
                and e.filename.lower().endswith(EXCEL_EXTS)
            ]
            if not xlsx:
                logger.warning(f'No XLSX files found in {remote_dir}')
                return None

            xlsx.sort(key=lambda e: e.st_mtime or 0, reverse=True)
            newest = xlsx[0]
            remote_path = f'{remote_dir.rstrip("/")}/{newest.filename}'

            ts = datetime.now().strftime('%Y%m%d_%H%M')
            local_name = f'{prefix}{ts}_{newest.filename}'
            return self._download(sftp, remote_path, local_name)

        except Exception as e:
            logger.error(f'download_latest_xlsx({remote_dir}): {e}')
            return None
        finally:
            if sftp: sftp.close()
            if ssh:  ssh.close()

    def download_latest_subdir_files(self, root_dir, tech_filename_map, prefix=''):
        """
        Find the newest subdirectory inside root_dir, then download one
        file per technology using tech_filename_map = {tech: filename}.
        Returns {tech: local_path or None}.

        Used for the Metadata server which stores snapshot folders named
        by date (e.g. 20250215/) each containing 5 tech Excel files.

        If filenames inside the subdir are not fixed, pass None as the
        filename value and the method will download the first XLSX found
        for that slot.
        """
        ssh, sftp = None, None
        results = {t: None for t in tech_filename_map}
        try:
            ssh, sftp = self._open()

            # Find newest subdirectory
            entries = sftp.listdir_attr(root_dir)
            subdirs = [
                e for e in entries
                if stat.S_ISDIR(e.st_mode)
            ]
            if not subdirs:
                logger.warning(f'No subdirectories found in {root_dir}')
                return results

            subdirs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
            latest_subdir = f'{root_dir.rstrip("/")}/{subdirs[0].filename}'
            logger.info(f'Latest metadata subdir: {latest_subdir}')

            # List files in that subdir
            subdir_entries = sftp.listdir_attr(latest_subdir)
            xlsx_files = [
                e for e in subdir_entries
                if not stat.S_ISDIR(e.st_mode)
                and e.filename.lower().endswith(EXCEL_EXTS)
            ]
            xlsx_files.sort(key=lambda e: e.st_mtime or 0, reverse=True)

            ts = datetime.now().strftime('%Y%m%d_%H%M')

            for tech, expected_name in tech_filename_map.items():
                # Find the matching file (exact name or first xlsx as fallback)
                match = None
                if expected_name:
                    for e in xlsx_files:
                        if e.filename.lower() == expected_name.lower():
                            match = e
                            break
                if not match and xlsx_files:
                    # No exact name — pick first unclaimed xlsx
                    match = xlsx_files.pop(0) if xlsx_files else None

                if not match:
                    logger.warning(f'No file for tech={tech} in {latest_subdir}')
                    continue

                remote_path  = f'{latest_subdir}/{match.filename}'
                local_name   = f'{prefix}{tech}_{ts}_{match.filename}'
                results[tech] = self._download(sftp, remote_path, local_name)

        except Exception as e:
            logger.error(f'download_latest_subdir_files({root_dir}): {e}')
        finally:
            if sftp: sftp.close()
            if ssh:  ssh.close()

        return results

    def download_file_exact(self, remote_path, local_filename=None):
        """Download a single file by its full remote path."""
        ssh, sftp = None, None
        try:
            ssh, sftp = self._open()
            if not local_filename:
                local_filename = os.path.basename(remote_path)
            return self._download(sftp, remote_path, local_filename)
        except Exception as e:
            logger.error(f'download_file_exact({remote_path}): {e}')
            return None
        finally:
            if sftp: sftp.close()
            if ssh:  ssh.close()
