"""
Parse Femto raw TGZ/XML files and prepare metadata tables.

Output:
- SQLite table in METADATA_DB: femto_metadata
- SQLite table in METADATA_DB: femto_kpi_catalog
"""

from __future__ import annotations

import os
import re
import sqlite3
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_config import METADATA_DB, PROJECT_ROOT


RAW_FEMTO_DIR = Path(PROJECT_ROOT) / "raw" / "femto"


def _extract_tag_text(root: ET.Element, tag: str) -> str:
    node = root.find(f".//{tag}")
    return (node.text or "").strip() if node is not None and node.text is not None else ""


def _parse_neun_kv(neun: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in str(neun or "").split(","):
        s = part.strip()
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _safe_member_text(tgz_path: Path) -> tuple[str, str]:
    """
    Return (member_name, xml_text) from first regular file in archive.
    """
    with tarfile.open(tgz_path, "r:gz") as tf:
        member = next((m for m in tf.getmembers() if m.isfile()), None)
        if member is None:
            return "", ""
        fh = tf.extractfile(member)
        if fh is None:
            return member.name, ""
        data = fh.read()
        return member.name, data.decode("utf-8", "replace")


def _parse_one_archive(tgz_path: Path) -> tuple[dict, set[str]] | None:
    member_name, xml_text = _safe_member_text(tgz_path)
    if not xml_text.strip():
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    cbt = _extract_tag_text(root, "cbt")
    mts = _extract_tag_text(root, "mts")
    gp = _extract_tag_text(root, "gp")
    neun = _extract_tag_text(root, "neun")
    nedn = _extract_tag_text(root, "nedn")
    nesw = _extract_tag_text(root, "nesw")
    ffv = _extract_tag_text(root, "ffv")
    vn = _extract_tag_text(root, "vn")
    st = _extract_tag_text(root, "st")
    sf = _extract_tag_text(root, "sf")

    neun_kv = _parse_neun_kv(neun)
    hnb_id = neun_kv.get("HNBId", "")
    fsn = neun_kv.get("Fsn", "")
    bsr_name = neun_kv.get("bSRName", "")
    op_mode = neun_kv.get("OpMode", "")

    managed_element = ""
    m = re.search(r"ManagedElement=([^,]+)", nedn)
    if m:
        managed_element = m.group(1).strip()

    mt_names = set()
    for mt in root.findall(".//mt"):
        txt = (mt.text or "").strip()
        if txt:
            mt_names.add(txt)

    rel_path = str(tgz_path.relative_to(RAW_FEMTO_DIR)).replace("\\", "/")
    row = {
        "archive_path": rel_path,
        "archive_name": tgz_path.name,
        "member_name": member_name,
        "cbt": cbt,
        "mts": mts,
        "gp_seconds": gp,
        "vendor_name": vn,
        "system_type": st,
        "ffv": ffv,
        "sf": sf,
        "hnb_id": hnb_id,
        "fsn": fsn,
        "bsr_name": bsr_name,
        "op_mode": op_mode,
        "managed_element": managed_element,
        "neun": neun,
        "nedn": nedn,
        "nesw": nesw,
        "kpi_count": len(mt_names),
    }
    return row, mt_names


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS femto_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_path TEXT NOT NULL,
            archive_name TEXT,
            member_name TEXT,
            cbt TEXT,
            mts TEXT,
            gp_seconds TEXT,
            vendor_name TEXT,
            system_type TEXT,
            ffv TEXT,
            sf TEXT,
            hnb_id TEXT,
            fsn TEXT,
            bsr_name TEXT,
            op_mode TEXT,
            managed_element TEXT,
            neun TEXT,
            nedn TEXT,
            nesw TEXT,
            kpi_count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_femto_metadata_archive ON femto_metadata(archive_path)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS femto_kpi_catalog (
            kpi_name TEXT PRIMARY KEY,
            first_seen_archive TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def main() -> int:
    if not RAW_FEMTO_DIR.exists():
        print(f"[error] raw femto path not found: {RAW_FEMTO_DIR}")
        return 1

    archives = sorted(RAW_FEMTO_DIR.rglob("*.tgz"))
    if not archives:
        print(f"[warn] no tgz files found under: {RAW_FEMTO_DIR}")
        return 0

    conn = sqlite3.connect(METADATA_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_tables(conn)

    upserts = 0
    parse_fail = 0
    all_kpis: dict[str, str] = {}

    for tgz in archives:
        parsed = _parse_one_archive(tgz)
        if not parsed:
            parse_fail += 1
            continue
        row, mt_names = parsed

        conn.execute(
            """
            INSERT INTO femto_metadata (
                archive_path, archive_name, member_name, cbt, mts, gp_seconds,
                vendor_name, system_type, ffv, sf, hnb_id, fsn, bsr_name, op_mode,
                managed_element, neun, nedn, nesw, kpi_count, updated_at
            ) VALUES (
                :archive_path, :archive_name, :member_name, :cbt, :mts, :gp_seconds,
                :vendor_name, :system_type, :ffv, :sf, :hnb_id, :fsn, :bsr_name, :op_mode,
                :managed_element, :neun, :nedn, :nesw, :kpi_count, CURRENT_TIMESTAMP
            )
            ON CONFLICT(archive_path) DO UPDATE SET
                archive_name=excluded.archive_name,
                member_name=excluded.member_name,
                cbt=excluded.cbt,
                mts=excluded.mts,
                gp_seconds=excluded.gp_seconds,
                vendor_name=excluded.vendor_name,
                system_type=excluded.system_type,
                ffv=excluded.ffv,
                sf=excluded.sf,
                hnb_id=excluded.hnb_id,
                fsn=excluded.fsn,
                bsr_name=excluded.bsr_name,
                op_mode=excluded.op_mode,
                managed_element=excluded.managed_element,
                neun=excluded.neun,
                nedn=excluded.nedn,
                nesw=excluded.nesw,
                kpi_count=excluded.kpi_count,
                updated_at=CURRENT_TIMESTAMP
            """,
            row,
        )
        upserts += 1

        for k in mt_names:
            if k not in all_kpis:
                all_kpis[k] = row["archive_path"]

    for kpi, first_archive in all_kpis.items():
        conn.execute(
            """
            INSERT INTO femto_kpi_catalog (kpi_name, first_seen_archive, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(kpi_name) DO UPDATE SET
                updated_at=CURRENT_TIMESTAMP
            """,
            (kpi, first_archive),
        )

    conn.commit()
    total_kpis = conn.execute("SELECT COUNT(*) FROM femto_kpi_catalog").fetchone()[0]
    total_rows = conn.execute("SELECT COUNT(*) FROM femto_metadata").fetchone()[0]
    conn.close()

    print(f"[done] archives_seen={len(archives)} metadata_upserts={upserts} parse_fail={parse_fail}")
    print(f"[done] femto_metadata_rows={total_rows} femto_kpi_catalog_rows={total_kpis} db={METADATA_DB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

