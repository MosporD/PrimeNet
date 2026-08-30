"""Flask-safe SON ML reads — sqlite + numpy/sklearn only, never import torch."""

from __future__ import annotations

from . import config as cfg
from . import store
from .models.treatment import attach_to_rows as attach_treatment_to_rows
from .models.treatment import score_proposal


def ml_status() -> dict:
    if cfg.env_disabled():
        return {"available": False, "disabled": True}
    try:
        status = store.store_status()
        status["disabled"] = False
        return status
    except Exception as exc:
        return {"available": False, "disabled": False, "error": str(exc)}


def score_map() -> dict[str, dict]:
    """cell_name lower -> latest score row."""
    if cfg.env_disabled():
        return {}
    try:
        rows = store.load_latest_scores()
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        key = str(row.get("cell_name") or "").strip().lower()
        if not key:
            continue
        out[key] = row
        vendor = str(row.get("vendor") or "").strip().lower()
        if vendor:
            out[f"{vendor}|{key}"] = row
    return out


def top_cause(probs: dict | None) -> tuple[str, float]:
    if not probs:
        return "", 0.0
    name, val = max(probs.items(), key=lambda kv: float(kv[1] or 0))
    return str(name), float(val or 0)


def mean_anomaly(cells: list[str], scores: dict[str, dict]) -> float:
    vals = []
    for cell in cells or []:
        row = scores.get(str(cell or "").strip().lower())
        if row and row.get("anomaly_score") is not None:
            vals.append(float(row["anomaly_score"]))
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def save_feedback(username: str, rec_id: str, label: str) -> dict:
    return store.save_feedback(username, rec_id, label)


def score_load_balancing_rows(rows: list[dict], *, site_key_fields: tuple[str, ...] = ("mrbts", "site_id")) -> None:
    if cfg.env_disabled():
        return
    try:
        attach_treatment_to_rows(rows, site_key_fields=site_key_fields)
    except Exception:
        for row in rows or []:
            row.setdefault(
                "ml_treatment",
                {
                    "predicted_util_delta": None,
                    "predicted_mobility_delta": None,
                    "confidence": "none",
                    "model": "unavailable",
                    "note": "SON ML store not ready.",
                },
            )


def score_one_proposal(*, site_id: str | None, action: str | None) -> dict:
    if cfg.env_disabled():
        return {
            "predicted_util_delta": None,
            "predicted_mobility_delta": None,
            "confidence": "none",
            "model": "disabled",
        }
    return score_proposal(site_id=site_id, action=action)
