"""
SFTP Client
===========
Handles connecting to SFTP servers and downloading files.

Key methods
-----------
download_latest_xlsx(remote_dir, prefix, descend_into_newest_subdir=False)
    List all matching files under remote_dir (and PRS subdirs when enabled),
    log ``Found files:`` then ``Pulled latest file:``, and download the newest by mtime.
    If ``descend_into_newest_subdir`` is True (Huawei PRS), try the newest
    immediate child directory first, then fall back to files in ``remote_dir``.

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

EXCEL_EXTS = ('.xlsx', '.xls', '.csv')
DATA_EXTS  = ('.xlsx', '.xls', '.csv')   # used for metadata which may be CSV


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

    def _suffix_ok(self, name: str, excel_exts: tuple) -> bool:
        lower = name.lower()
        return any(lower.endswith(ext) for ext in excel_exts)

    def _build_prs_search_dirs(self, sftp, base: str, remote_dir: str, max_depth: int = 4):
        """
        Build ordered list of directories to scan for Excel files.

        PRS/U2000 often uses: ``remote_dir/<date_or_batch>/`` or one more level
        ``.../<date>/<task>/``. An empty *newest* folder is common; we must try
        every immediate subdir (newest first), then each one's immediate
        subdirs (newest first), then ``remote_dir`` itself.
        """
        search_dirs = [remote_dir]
        seen = {remote_dir.rstrip('/').lower()}
        frontier = [(remote_dir, 0)]
        while frontier:
            current, depth = frontier.pop(0)
            if depth >= max_depth:
                continue
            try:
                entries = sftp.listdir_attr(current)
            except OSError as ex:
                logger.warning(f'listdir {current}: {ex}')
                continue
            subdirs = [e for e in entries if stat.S_ISDIR(e.st_mode)]
            subdirs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
            for sd in subdirs:
                nxt = f'{current.rstrip("/")}/{sd.filename}'
                key = nxt.rstrip('/').lower()
                if key in seen:
                    continue
                seen.add(key)
                search_dirs.append(nxt)
                frontier.append((nxt, depth + 1))
        return search_dirs

    def download_latest_xlsx(
        self,
        remote_dir,
        prefix='',
        descend_into_newest_subdir=False,
        excel_exts: tuple | None = None,
    ):
        """
        Collect every matching spreadsheet under ``remote_dir`` (and PRS subdirs),
        log them as **Found files**, then log **Pulled latest file** and download
        that one (newest remote ``st_mtime``).

        When ``descend_into_newest_subdir`` is True, U2000/PRS-style layouts are
        supported: every immediate subfolder under ``remote_dir`` is tried (newest
        mtime first), then each one's subfolders, then a flat ``remote_dir/*`` layout
        filtered by allowed extensions. This avoids missing files when the single
        "newest" folder is empty.
        """
        exts = excel_exts if excel_exts is not None else EXCEL_EXTS
        ssh, sftp = None, None
        try:
            ssh, sftp = self._open()
            base = remote_dir.rstrip('/')
            search_dirs = []
            if descend_into_newest_subdir:
                search_dirs = self._build_prs_search_dirs(sftp, base, remote_dir)
                logger.info(
                    'SFTP: PRS search order under %s (%s dirs try-first)',
                    remote_dir,
                    len(search_dirs),
                )
            else:
                search_dirs = [remote_dir]

            # Every matching file in every searched directory (global newest wins).
            all_matches = []
            for td in search_dirs:
                try:
                    ent = sftp.listdir_attr(td)
                except OSError as ex:
                    logger.warning(f'listdir {td}: {ex}')
                    continue
                for e in ent:
                    if stat.S_ISDIR(e.st_mode):
                        continue
                    if not self._suffix_ok(e.filename, exts):
                        continue
                    mtime = float(e.st_mtime or 0)
                    remote_path = f'{td.rstrip("/")}/{e.filename}'
                    all_matches.append((mtime, remote_path))

            if not all_matches:
                logger.warning(
                    'No matching spreadsheet files under %s (searched %s dirs; extensions=%s)',
                    remote_dir,
                    len(search_dirs),
                    exts,
                )
                return None

            all_matches.sort(key=lambda x: x[0], reverse=True)
            listing = '\n  '.join(m[1] for m in all_matches)
            logger.info(
                'Found files (%s under %s):\n  %s',
                len(all_matches),
                remote_dir,
                listing,
            )
            best_mtime, remote_path = all_matches[0]
            newest_name = remote_path.rsplit('/', 1)[-1]
            logger.info('Pulled latest file: %s (remote mtime=%s)', remote_path, int(best_mtime))
            ts = datetime.now().strftime('%Y%m%d_%H%M')
            local_name = f'{prefix}{ts}_{newest_name}'
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

            # List files in that subdir (XLSX or CSV)
            subdir_entries = sftp.listdir_attr(latest_subdir)
            xlsx_files = [
                e for e in subdir_entries
                if not stat.S_ISDIR(e.st_mode)
                and e.filename.lower().endswith(DATA_EXTS)
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

    def download_all_xlsx_from_subfolders(self, root_dir, prefix=''):
        """
        Find the newest subdirectory inside root_dir, enter it, then
        descend into each subfolder within it and download ALL Excel/CSV
        files found there.

        Folder structure expected:
            root_dir/
              <latest_dated_folder>/     ← newest by mtime
                <tech_subfolder>/        ← e.g. 2G, 3G, 4G-FDD …
                  file1.xlsx
                  file2.xlsx
                  ...

        Returns {subfolder_name: [local_path, ...]}

        Falls back gracefully if the latest folder has no subfolders (flat
        structure) — in that case all Excel files are returned under the
        key '_root'.
        """
        ssh, sftp = None, None
        results = {}
        try:
            ssh, sftp = self._open()

            # ── 1. Find newest subdirectory in root_dir ──────────────────
            entries = sftp.listdir_attr(root_dir)
            subdirs = [e for e in entries if stat.S_ISDIR(e.st_mode)]
            if not subdirs:
                logger.warning(f'No subdirectories found in {root_dir}')
                return results

            subdirs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
            latest_dir = f'{root_dir.rstrip("/")}/{subdirs[0].filename}'
            logger.info(f'Latest metadata folder: {latest_dir}')

            # ── 2. List contents of the latest folder ────────────────────
            inner_entries = sftp.listdir_attr(latest_dir)
            inner_subdirs = [e for e in inner_entries if stat.S_ISDIR(e.st_mode)]
            ts = datetime.now().strftime('%Y%m%d_%H%M')

            if inner_subdirs:
                # Expected path: root/latest/<subfolder>/*.xlsx
                for sub in inner_subdirs:
                    sub_path = f'{latest_dir}/{sub.filename}'
                    sub_entries = sftp.listdir_attr(sub_path)
                    xlsx_files = [
                        e for e in sub_entries
                        if not stat.S_ISDIR(e.st_mode)
                        and e.filename.lower().endswith(DATA_EXTS)
                    ]
                    if not xlsx_files:
                        logger.info(f'No Excel files in subfolder {sub_path}')
                        continue

                    downloaded = []
                    for f in xlsx_files:
                        remote_path = f'{sub_path}/{f.filename}'
                        local_name  = f'{prefix}{sub.filename}_{ts}_{f.filename}'
                        local_path  = self._download(sftp, remote_path, local_name)
                        if local_path:
                            downloaded.append(local_path)
                    if downloaded:
                        results[sub.filename] = downloaded
            else:
                # Flat structure — files sit directly in latest_dir (no tech subfolders).
                # Key each file by its stem (e.g. "2G-2025-12-03" or "2G") so the
                # metadata processor can match it to the right technology column map.
                xlsx_files = [
                    e for e in inner_entries
                    if not stat.S_ISDIR(e.st_mode)
                    and e.filename.lower().endswith(DATA_EXTS)
                ]
                if not xlsx_files:
                    logger.warning(f'No Excel/CSV files found in {latest_dir}')
                else:
                    for f in xlsx_files:
                        remote_path = f'{latest_dir}/{f.filename}'
                        local_name  = f'{prefix}{ts}_{f.filename}'
                        local_path  = self._download(sftp, remote_path, local_name)
                        if local_path:
                            stem = os.path.splitext(f.filename)[0]
                            results[stem] = [local_path]

        except Exception as e:
            logger.error(f'download_all_xlsx_from_subfolders({root_dir}): {e}')
        finally:
            if sftp: sftp.close()
            if ssh:  ssh.close()

        return results

    def download_files_from_latest_subdir(self, root_dir, prefix=''):
        """
        Find the newest subdirectory inside root_dir, then download ALL
        data files (CSV / XLSX) that sit DIRECTLY in it — no recursion
        into inner sub-subfolders.

        Folder structure expected:
            root_dir/
              <latest_dated_folder>/     ← newest by mtime
                file1.csv                ← downloaded
                file2.csv                ← downloaded
                some_subfolder/          ← IGNORED

        Returns {file_stem: [local_path]}
        """
        ssh, sftp = None, None
        results = {}
        try:
            ssh, sftp = self._open()

            # Find newest subdirectory at root
            entries = sftp.listdir_attr(root_dir)
            subdirs = [e for e in entries if stat.S_ISDIR(e.st_mode)]
            if not subdirs:
                logger.warning(f'No subdirectories found in {root_dir}')
                return results

            subdirs.sort(key=lambda e: e.st_mtime or 0, reverse=True)
            latest_dir = f'{root_dir.rstrip("/")}/{subdirs[0].filename}'
            logger.info(f'Latest metadata folder: {latest_dir}')

            # Download only files at the first level (skip subdirectories)
            inner_entries = sftp.listdir_attr(latest_dir)
            data_files = [
                e for e in inner_entries
                if not stat.S_ISDIR(e.st_mode)
                and e.filename.lower().endswith(DATA_EXTS)
            ]

            if not data_files:
                logger.warning(f'No data files found at first tier of {latest_dir}')
                return results

            meta_listing = '\n  '.join(f'{latest_dir}/{e.filename}' for e in data_files)
            logger.info(
                'Found files (%s in latest snapshot):\n  %s',
                len(data_files),
                meta_listing,
            )
            logger.info('Downloading all %s metadata file(s)…', len(data_files))

            ts = datetime.now().strftime('%Y%m%d_%H%M')
            for f in data_files:
                remote_path = f'{latest_dir}/{f.filename}'
                local_name  = f'{prefix}{ts}_{f.filename}'
                local_path  = self._download(sftp, remote_path, local_name)
                if local_path:
                    stem = os.path.splitext(f.filename)[0]
                    results[stem] = [local_path]

        except Exception as e:
            logger.error(f'download_files_from_latest_subdir({root_dir}): {e}')
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
