"""PCI / PSC neighbour-relation audit.

Conflict Map already scores geographic co-band reuse (distance plus azimuth
versus inter-site bearing). It never reads the neighbour graph, so it cannot
see the faults that only exist between *defined relations*. This module covers
those:

  * **Collision** — a cell and one of its own neighbours share a PCI. The
    handover target is ambiguous, so handovers to it fail outright.
  * **Confusion** — two distinct neighbours of the same cell share a PCI. The
    serving cell cannot resolve which one a UE reported.
  * **mod3 / mod30** — modulo collisions between strong neighbours (LTE/NR
    only): mod3 drives PSS/SSS and DMRS interference, mod30 drives PUCCH/SRS.

Collision and confusion are hard faults — a flagged pair is verifiably right or
wrong by inspection. The modulo checks are interference *risk*, so they are
gated on handover volume: every network has mod3 pairs, only the busy ones are
worth an engineer's time.

Known limits: cell metadata carries `frequency_band` but no EARFCN/ARFCN, so
same-band is used as the co-frequency proxy; and it carries no PRACH root
sequence index, so RSI conflicts are out of scope until that is ingested.
"""

from __future__ import annotations

from . import metadata, neighbor
from .scoring import issue, summarize, utc_now_iso

# A mod3/mod30 pair only matters where real traffic crosses it.
DEFAULT_MIN_MOD_ATTEMPTS = 50.0


def pci_value(raw: object) -> int | None:
    """Parse a PCI/PSC cell attribute into an int, or None when unusable."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = int(float(text))
    except (TypeError, ValueError):
        return None
    # LTE 0-503, NR 0-1007, UMTS PSC 0-511; anything outside is bad metadata.
    return value if 0 <= value <= 1007 else None


def is_lte_or_nr(technology: object) -> bool:
    """mod3/mod30 are LTE/NR concepts; 2G/3G relations are skipped."""
    tech = str(technology or "").upper()
    return tech.startswith("4G") or tech.startswith("5G") or "LTE" in tech or "NR" in tech


def _pair_key(a: str, b: str) -> tuple[str, str]:
    """Direction-independent key so A→B and B→A collapse to one finding."""
    left, right = str(a or "").lower(), str(b or "").lower()
    return (left, right) if left <= right else (right, left)


def classify_relations(
    relations: list[dict],
    pci_by_cell: dict[str, int],
    *,
    band_by_cell: dict[str, str] | None = None,
    min_mod_attempts: float = DEFAULT_MIN_MOD_ATTEMPTS,
) -> list[dict]:
    """Return PCI findings for a list of neighbour relations.

    Pure function over plain dicts so it can be unit-tested without a database.
    Each relation needs ``source_cell``/``target_cell``; ``ho_attempts`` and
    ``technology`` refine the modulo checks when present.
    """
    bands = band_by_cell or {}
    findings: list[dict] = []
    seen_pairs: set[tuple[str, tuple[str, str]]] = set()
    # source cell -> pci -> set of neighbour cells reporting that pci
    by_source: dict[str, dict[int, set[str]]] = {}
    source_meta: dict[str, dict] = {}

    for rel in relations:
        src = str(rel.get("source_cell") or "").strip()
        tgt = str(rel.get("target_cell") or "").strip()
        if not src or not tgt or src.lower() == tgt.lower():
            continue
        src_pci = pci_by_cell.get(src.lower())
        tgt_pci = pci_by_cell.get(tgt.lower())
        if src_pci is None or tgt_pci is None:
            continue

        src_band = str(bands.get(src.lower()) or "")
        tgt_band = str(bands.get(tgt.lower()) or "")
        # Same-band is the co-frequency proxy; when either band is unknown we
        # still compare rather than silently dropping the relation.
        same_band = not src_band or not tgt_band or src_band == tgt_band

        source_meta.setdefault(src, rel)
        if same_band:
            by_source.setdefault(src, {}).setdefault(tgt_pci, set()).add(tgt)

        attempts = rel.get("ho_attempts")
        try:
            attempts = float(attempts) if attempts is not None else 0.0
        except (TypeError, ValueError):
            attempts = 0.0

        # ── Collision: the relation's two ends share a PCI ──────────────────
        if src_pci == tgt_pci and same_band:
            key = ("collision", _pair_key(src, tgt))
            if key not in seen_pairs:
                seen_pairs.add(key)
                findings.append({
                    "kind": "collision",
                    "source_cell": src,
                    "target_cells": [tgt],
                    "pci": src_pci,
                    "attempts": attempts,
                    "relation": rel,
                })
            continue

        # mod3/mod30 interference is co-frequency, so it needs the same band
        # just as collision does.
        if not same_band:
            continue
        if not is_lte_or_nr(rel.get("technology")):
            continue
        if attempts < min_mod_attempts:
            continue

        # ── Modulo interference between neighbours that carry real traffic ──
        if src_pci % 3 == tgt_pci % 3:
            key = ("mod3", _pair_key(src, tgt))
            if key not in seen_pairs:
                seen_pairs.add(key)
                findings.append({
                    "kind": "mod3",
                    "source_cell": src,
                    "target_cells": [tgt],
                    "pci": src_pci,
                    "target_pci": tgt_pci,
                    "attempts": attempts,
                    "relation": rel,
                })
        if src_pci % 30 == tgt_pci % 30:
            key = ("mod30", _pair_key(src, tgt))
            if key not in seen_pairs:
                seen_pairs.add(key)
                findings.append({
                    "kind": "mod30",
                    "source_cell": src,
                    "target_cells": [tgt],
                    "pci": src_pci,
                    "target_pci": tgt_pci,
                    "attempts": attempts,
                    "relation": rel,
                })

    # ── Confusion: one cell, two neighbours, one PCI ────────────────────────
    for src, pci_map in by_source.items():
        for pci, targets in pci_map.items():
            if len(targets) < 2:
                continue
            findings.append({
                "kind": "confusion",
                "source_cell": src,
                "target_cells": sorted(targets),
                "pci": pci,
                "attempts": 0.0,
                "relation": source_meta.get(src, {}),
            })
    return findings


_KIND_SPEC = {
    "collision": {
        "score": 95.0,
        "title": "PCI collision: {src} and neighbour share PCI {pci}",
        "summary": "{src} and its neighbour {tgt} both use PCI {pci} on the same band. Handovers to this relation cannot resolve a unique target.",
        "recommendation": "Replan the PCI on one of the two cells, then re-verify the relation's handover success rate.",
    },
    "confusion": {
        "score": 90.0,
        "title": "PCI confusion: {n} neighbours of {src} share PCI {pci}",
        "summary": "{src} has {n} defined neighbours all using PCI {pci}: {tgt}. The serving cell cannot tell which one a UE reported.",
        "recommendation": "Replan the PCI on all but one of the conflicting neighbours, or remove the relations that should not exist.",
    },
    "mod3": {
        "score": 55.0,
        "title": "PCI mod3 collision: {src} ↔ neighbour",
        "summary": "{src} (PCI {pci}) and {tgt} (PCI {tpci}) share PCI mod 3 across {att} handover attempts — PSS/SSS and DMRS interference risk.",
        "recommendation": "Where this relation carries significant traffic, replan one PCI onto a different mod3 group.",
    },
    "mod30": {
        "score": 35.0,
        "title": "PCI mod30 collision: {src} ↔ neighbour",
        "summary": "{src} (PCI {pci}) and {tgt} (PCI {tpci}) share PCI mod 30 across {att} handover attempts — PUCCH/SRS interference risk.",
        "recommendation": "Consider a PCI change if uplink control-channel performance on this pair is degraded.",
    },
}


def _finding_to_issue(finding: dict, cell_meta: dict) -> dict:
    spec = _KIND_SPEC[finding["kind"]]
    src = finding["source_cell"]
    targets = finding["target_cells"]
    meta = cell_meta.get(src.lower(), {})
    rel = finding.get("relation") or {}
    fmt = {
        "src": src,
        "tgt": ", ".join(targets[:4]) + ("…" if len(targets) > 4 else ""),
        "pci": finding.get("pci"),
        "tpci": finding.get("target_pci"),
        "n": len(targets),
        "att": int(finding.get("attempts") or 0),
    }
    score = float(spec["score"])
    if finding["kind"] == "confusion":
        # More colliding neighbours means a worse ambiguity.
        score = min(100.0, score + (len(targets) - 2) * 2.5)
    return issue(
        module="PCI Audit",
        category="PCI / Interference",
        title=spec["title"].format(**fmt),
        summary=spec["summary"].format(**fmt),
        score=score,
        cells=[src, *targets],
        site_id=str(rel.get("source_site_id") or meta.get("site_id") or ""),
        area=str(meta.get("area") or ""),
        vendor=str(rel.get("vendor") or meta.get("vendor") or ""),
        technology=str(rel.get("technology") or meta.get("technology") or ""),
        evidence={
            "check": finding["kind"],
            "pci": finding.get("pci"),
            "target_pci": finding.get("target_pci"),
            "conflicting_neighbours": targets,
            "ho_attempts": finding.get("attempts"),
            "source_band": meta.get("frequency_band"),
        },
        recommendation=spec["recommendation"],
        source_url="/pci-audit",
    )


def pci_audit(
    *,
    vendor: str = "all",
    technology: str = "all",
    area: str = "",
    limit: int = 300,
    min_mod_attempts: float = DEFAULT_MIN_MOD_ATTEMPTS,
) -> dict:
    """Audit PCI assignment across defined neighbour relations."""
    relations = neighbor.load_neighbor_lines(
        vendor, technology, min_attempts=1, max_lines=max(2000, limit * 8)
    )
    cell_meta = metadata.cell_index()

    pci_by_cell: dict[str, int] = {}
    band_by_cell: dict[str, str] = {}
    for key, row in cell_meta.items():
        parsed = pci_value(row.get("pci"))
        if parsed is not None:
            pci_by_cell[key] = parsed
        band = str(row.get("frequency_band") or "").strip()
        if band:
            band_by_cell[key] = band

    findings = classify_relations(
        relations,
        pci_by_cell,
        band_by_cell=band_by_cell,
        min_mod_attempts=min_mod_attempts,
    )

    rows = [_finding_to_issue(f, cell_meta) for f in findings]
    if area and area.lower() != "all":
        rows = [r for r in rows if str(r.get("area") or "").lower() == area.lower()]
    rows.sort(key=lambda r: -float(r.get("score") or 0))
    rows = rows[: max(1, int(limit))]

    covered = sum(1 for r in relations if str(r.get("source_cell") or "").lower() in pci_by_cell)
    return {
        "generated_at": utc_now_iso(),
        "summary": summarize(rows),
        "issues": rows,
        "coverage": {
            "relations_scanned": len(relations),
            "relations_with_pci": covered,
            "cells_with_pci": len(pci_by_cell),
            "cells_total": len(cell_meta),
        },
        "note": (
            "Collision and confusion are hard faults; mod3/mod30 are interference risk and "
            f"are only reported above {int(min_mod_attempts)} handover attempts. Same-band is used "
            "as the co-frequency proxy (metadata has no EARFCN), and RSI/PRACH conflicts are out "
            "of scope until root-sequence data is ingested. Geographic co-band reuse is covered "
            "by Conflict Map."
        ),
    }
