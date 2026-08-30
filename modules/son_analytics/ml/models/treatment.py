"""Read-only treatment-effect scoring for AMLE / CellMLB proposals."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import numpy as np

from .. import config as cfg
from .. import store

logger = logging.getLogger(__name__)

_MODEL_NAME = "treatment_ridge.joblib"


def _parse_day(value: str | None) -> datetime | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def _kpi_delta(history: list[dict], changed_at: str | None) -> dict[str, float] | None:
    day = _parse_day(changed_at)
    if not day:
        return None
    by_day = {str(h.get("day")): (h.get("kpis") or {}) for h in history}
    before_keys = [(day - timedelta(days=d)).strftime("%Y-%m-%d") for d in (1, 2, 3)]
    after_keys = [(day + timedelta(days=d)).strftime("%Y-%m-%d") for d in (1, 2, 3)]
    before = [by_day[k] for k in before_keys if k in by_day]
    after = [by_day[k] for k in after_keys if k in by_day]
    if not before or not after:
        return None
    out: dict[str, float] = {}
    for cat in cfg.KPI_CATEGORIES:
        bvals = [float(x[cat]) for x in before if cat in x]
        avals = [float(x[cat]) for x in after if cat in x]
        if bvals and avals:
            out[cat] = float(np.mean(avals) - np.mean(bvals))
    return out or None


def _action_code(action: str) -> float:
    text = str(action or "").lower()
    if "reduce" in text or "less" in text:
        return -1.0
    if "increase" in text or "more" in text:
        return 1.0
    return 0.0


def train_treatment() -> dict:
    """Fit Ridge on historical CM changes vs KPI deltas; fall back to heuristic."""
    from core.radio import cm_store

    samples_x: list[list[float]] = []
    samples_y: list[list[float]] = []
    try:
        changes = cm_store.detect_changes(limit=800)
    except Exception:
        changes = []

    for ch in changes:
        cell = str(ch.get("cell_name") or "").strip()
        vendor = str(ch.get("vendor") or "").strip().lower() or "nokia"
        if not cell:
            continue
        hist = store.load_cell_history(cell, vendor, cfg.TECHNOLOGY)
        if len(hist) < 4:
            continue
        delta = _kpi_delta(hist, ch.get("changed_at"))
        if not delta:
            continue
        latest = hist[-1].get("kpis") or {}
        x = [float(latest.get(cat) or 0.0) for cat in cfg.KPI_CATEGORIES]
        x.append(_action_code(str(ch.get("parameter") or "")))
        y = [float(delta.get("Utilization") or 0.0), float(delta.get("Mobility") or 0.0)]
        samples_x.append(x)
        samples_y.append(y)

    model_path = os.path.join(store.model_dir(), _MODEL_NAME)
    if len(samples_x) < 20:
        store.save_treatment_meta(
            sample_count=len(samples_x),
            model_path=None,
            heuristic=True,
            notes="too few CM+PM pairs; using action heuristic",
        )
        if os.path.isfile(model_path):
            try:
                os.remove(model_path)
            except OSError:
                pass
        return {"heuristic": True, "sample_count": len(samples_x)}

    from sklearn.linear_model import Ridge
    from sklearn.multioutput import MultiOutputRegressor
    import joblib

    model = MultiOutputRegressor(Ridge(alpha=1.0))
    model.fit(np.asarray(samples_x, dtype=float), np.asarray(samples_y, dtype=float))
    joblib.dump(model, model_path)
    store.save_treatment_meta(
        sample_count=len(samples_x),
        model_path=model_path,
        heuristic=False,
        notes="ridge on CM change → util/mobility delta",
    )
    return {"heuristic": False, "sample_count": len(samples_x), "model_path": model_path}


def _site_feature(site_key: str) -> list[float] | None:
    rows = store.load_latest_cell_days()
    if not site_key:
        return None
    needle = str(site_key).strip().lower()
    matched = []
    for row in rows:
        site = str(row.get("site_id") or "").strip().lower()
        cell = str(row.get("cell_name") or "").strip().lower()
        if needle and (needle == site or cell.startswith(needle) or needle in cell):
            matched.append(row)
    if not matched:
        return None
    vec = []
    for cat in cfg.KPI_CATEGORIES:
        vals = [float((r.get("kpis") or {}).get(cat) or 0.0) for r in matched]
        vec.append(float(np.mean(vals)) if vals else 0.0)
    return vec


def heuristic_score(action: str) -> dict:
    code = _action_code(action)
    return {
        "predicted_util_delta": round(-4.0 * code, 2),
        "predicted_mobility_delta": round(0.3 * code, 2),
        "confidence": "low",
        "model": "heuristic",
        "note": "Expected direction only — not a trained treatment model.",
    }


def score_proposal(*, site_id: str | None, action: str | None) -> dict:
    meta = store.load_treatment_meta() or {}
    feat = _site_feature(str(site_id or ""))
    action_s = str(action or "")
    if not feat or meta.get("heuristic") or not meta.get("model_path"):
        out = heuristic_score(action_s)
        if not feat:
            out["note"] = "No matching site cells in SON ML store; heuristic only."
        return out
    try:
        import joblib

        model = joblib.load(meta["model_path"])
        x = np.asarray([feat + [_action_code(action_s)]], dtype=float)
        pred = model.predict(x)[0]
        return {
            "predicted_util_delta": round(float(pred[0]), 2),
            "predicted_mobility_delta": round(float(pred[1]), 2),
            "confidence": "medium",
            "model": "ridge",
            "note": "Read-only forecast from historical CM vs PM. Does not apply changes.",
        }
    except Exception:
        logger.exception("Treatment model load/predict failed")
        return heuristic_score(action_s)


def attach_to_rows(rows: list[dict], *, site_key_fields: tuple[str, ...] = ("mrbts", "site_id")) -> None:
    for row in rows or []:
        site = ""
        for key in site_key_fields:
            val = row.get(key)
            if val not in (None, ""):
                site = str(val)
                break
        if not site:
            sector = str(row.get("sector_id") or "")
            if "_" in sector:
                site = sector.split("_", 1)[0]
            elif "-" in sector:
                site = sector.split("-", 1)[0]
        action = row.get("action") or ""
        row["ml_treatment"] = score_proposal(site_id=site, action=str(action))
