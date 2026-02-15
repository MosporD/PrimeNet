"""
SFTP Client
Handles connecting to SFTP servers and downloading files.
"""

import os
import logging
import paramiko
from datetime import datetime

logger = logging.getLogger(__name__)


class SFTPClient:
    def __init__(self, host, port, username, password, remote_dir, local_dir):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.remote_dir = remote_dir
        self.local_dir = local_dir
        os.makedirs(local_dir, exist_ok=True)

    def download_file(self, remote_filename, local_filename=None):
        """
        Download a single file from the SFTP server.
        Returns local file path on success, None on failure.
        """
        if not local_filename:
            local_filename = remote_filename

        local_path = os.path.join(self.local_dir, local_filename)
        remote_path = os.path.join(self.remote_dir, remote_filename).replace('\\', '/')

        ssh = None
        sftp = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=30
            )
            sftp = ssh.open_sftp()
            sftp.get(remote_path, local_path)
            logger.info(f'Downloaded {remote_path} -> {local_path}')
            return local_path

        except Exception as e:
            logger.error(f'Failed to download {remote_path}: {e}')
            return None

        finally:
            if sftp:
                sftp.close()
            if ssh:
                ssh.close()

    def download_all(self, files_dict):
        """
        Download multiple files defined as {technology: filename}.
        Returns dict of {technology: local_path or None}.
        """
        results = {}
        for tech, filename in files_dict.items():
            if not filename:
                logger.warning(f'No filename configured for {tech}, skipping.')
                results[tech] = None
                continue
            # Stamp local file with timestamp to avoid overwriting
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            local_name = f'{tech}_{timestamp}_{filename}'
            results[tech] = self.download_file(filename, local_name)
        return results
