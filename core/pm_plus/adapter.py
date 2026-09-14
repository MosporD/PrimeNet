"""
Vendor adapter seam for Performance Explorer Plus.

Nokia (live)
------------
``NokiaNbiAdapter`` parses TS 32.435 ``.gz`` / ``.xml`` via
``nokia_parser.iter_samples_from_path``. Live SFTP discovery/download is
implemented in ``core.pm_plus.ingest`` (not on the adapter class) so the
worker can own connection pooling and ledger claims.

Huawei (future)
---------------
When Huawei SFTP paths become available:

1. Implement ``HuaweiNbiAdapter.list_remote_files`` / ``download`` / ``iter_samples``
   for the Huawei counter file format (likely CSV/XML under PRS or NBI drop dirs).
2. Map samples into the same ``CounterSample`` shape (bucket_ts, object_dn,
   family, counter_id, value, vendor='huawei').
3. Call the existing ``write_samples_to_db`` / ledger path with ``vendor='huawei'``.
4. Enable the UI vendor filter (currently Nokia-only).

Do not invent a second warehouse schema — dims/facts are vendor-tagged.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from core.pm_plus.nokia_parser import CounterSample, iter_samples_from_path, parse_file


@dataclass(frozen=True)
class RemoteFileRef:
    host: str
    stream: str
    bucket: str
    relpath: str
    size_bytes: int | None = None
    mtime_epoch: float | None = None
    remote_full_path: str = ""


class VendorAdapter(Protocol):
    """Mediation contract shared by Nokia and future Huawei adapters."""

    vendor: str

    def list_remote_files(self, *, max_buckets: int = 4) -> list[RemoteFileRef]:
        """Discover recent ROP files on the vendor SFTP tree."""
        ...

    def download(self, ref: RemoteFileRef, dest: Path) -> Path:
        """Download one remote file to dest (file path)."""
        ...

    def iter_samples(self, local_path: Path) -> Iterator[CounterSample]:
        """Parse a local file into canonical counter samples."""
        ...


class NokiaNbiAdapter:
    """Nokia OSS NBI .gz (TS 32.435) adapter — parse path is live; SFTP via ingest."""

    vendor = "nokia"

    def list_remote_files(self, *, max_buckets: int = 4) -> list[RemoteFileRef]:
        raise NotImplementedError(
            "Use core.pm_plus.ingest.discover_remote_files for live SFTP listing"
        )

    def download(self, ref: RemoteFileRef, dest: Path) -> Path:
        raise NotImplementedError("Use core.pm_plus.ingest.download_file for live SFTP")

    def iter_samples(self, local_path: Path) -> Iterator[CounterSample]:
        return iter_samples_from_path(local_path)

    def parse(self, local_path: Path):
        return parse_file(local_path)


class HuaweiNbiAdapter:
    """Placeholder until Huawei raw SFTP paths are provided."""

    vendor = "huawei"

    def list_remote_files(self, *, max_buckets: int = 4) -> list[RemoteFileRef]:
        raise NotImplementedError(
            "Huawei NBI paths are not configured yet — see module docstring"
        )

    def download(self, ref: RemoteFileRef, dest: Path) -> Path:
        raise NotImplementedError("Huawei NBI paths are not configured yet")

    def iter_samples(self, local_path: Path) -> Iterator[CounterSample]:
        raise NotImplementedError(
            "Implement Huawei counter-file parser → CounterSample when paths exist"
        )


def get_adapter(vendor: str = "nokia") -> VendorAdapter:
    v = (vendor or "nokia").strip().lower()
    if v == "nokia":
        return NokiaNbiAdapter()
    if v == "huawei":
        return HuaweiNbiAdapter()
    raise ValueError(f"Unknown vendor adapter: {vendor}")
