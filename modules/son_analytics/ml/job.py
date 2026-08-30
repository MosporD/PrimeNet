"""Offline SON ML build — isolated subprocess, never imported by Flask request handlers for torch."""

from __future__ import annotations

import logging
import time

from . import config as cfg
from . import store
from .features import build_cell_days, feature_matrix, latest_rows
from .labels import collect_weak_labels
from .models.anomaly import fit_anomaly
from .models.cause import fit_cause
from .models.graph import graph_scores
from .models.spatial import cluster_spatial
from .models.treatment import train_treatment
from .neighbor_agg import attach_neighbor_features, neighbor_adjacency

logger = logging.getLogger(__name__)


def build_vendor_rat(vendor: str, rat: str = cfg.TECHNOLOGY, *, force: bool = False) -> dict:
    t0 = time.time()
    vkey = (vendor or "").strip().lower()
    fingerprint = store.pm_fingerprint(vkey, rat)
    if not force:
        meta = store.get_build_meta(vkey, rat)
        if meta and not meta.get("is_stale") and int(meta.get("score_count") or 0) > 0:
            return {
                "vendor": vkey,
                "rat": rat,
                "skipped": True,
                "reason": "up_to_date",
                "built_at": meta.get("built_at"),
            }

    cell_days = build_cell_days(vkey, rat)
    attach_neighbor_features(cell_days, vkey)
    store.replace_cell_days(vkey, rat, cell_days)

    latest = latest_rows(cell_days)
    if len(latest) < 8:
        store.replace_scores(vkey, rat, [])
        store.save_build_meta(
            vkey,
            rat,
            fingerprint=fingerprint,
            model_versions={"anomaly": "none"},
            row_count=len(cell_days),
            score_count=0,
            build_seconds=time.time() - t0,
        )
        return {
            "vendor": vkey,
            "rat": rat,
            "skipped": False,
            "row_count": len(cell_days),
            "score_count": 0,
            "reason": "too_few_cells",
            "seconds": round(time.time() - t0, 2),
        }

    names, matrix = feature_matrix(latest)
    import numpy as np

    x = np.asarray(matrix, dtype=float)
    anomaly = fit_anomaly(x, names)
    weak = collect_weak_labels(vkey, rat)
    causes = fit_cause(x, latest, weak)
    adj = neighbor_adjacency(vkey)
    gscores = graph_scores(latest, anomaly["embedding"], adj)
    spatial = cluster_spatial(latest, anomaly["embedding"])

    scores = []
    for i, row in enumerate(latest):
        scores.append({
            "cell_name": row["cell_name"],
            "vendor": vkey,
            "rat": rat,
            "day": row["day"],
            "anomaly_score": round(float(anomaly["anomaly_score"][i]), 2),
            "embedding": anomaly["embedding"][i],
            "top_kpis": anomaly["top_kpis"][i],
            "cause_probs": causes[i],
            "graph_score": round(float(gscores[i]), 2),
            "spatial_cluster_id": spatial[i].get("spatial_cluster_id") or "",
            "spatial_coherence": spatial[i].get("spatial_coherence") or "",
            "model_name": anomaly["model_name"],
            "fallback_used": anomaly["fallback_used"],
        })
    store.replace_scores(vkey, rat, scores)
    store.save_build_meta(
        vkey,
        rat,
        fingerprint=fingerprint,
        model_versions={
            "anomaly": anomaly["model_name"],
            "cause": "ovr-logreg" if weak else "heuristic",
            "graph": "sage" if cfg.torch_enabled() else "numpy",
            "spatial": "dbscan",
        },
        row_count=len(cell_days),
        score_count=len(scores),
        build_seconds=time.time() - t0,
    )
    elapsed = round(time.time() - t0, 2)
    logger.info("SON ML %s/%s: %s cells, %s scores in %ss", vkey, rat, len(cell_days), len(scores), elapsed)
    return {
        "vendor": vkey,
        "rat": rat,
        "skipped": False,
        "row_count": len(cell_days),
        "score_count": len(scores),
        "model": anomaly["model_name"],
        "seconds": elapsed,
    }


def build_all(*, force: bool = False) -> list[dict]:
    if cfg.env_disabled():
        return [{"skipped": True, "reason": "SON_DISABLE_ML"}]
    results: list[dict] = []
    for vendor in cfg.VENDORS:
        try:
            results.append(build_vendor_rat(vendor, cfg.TECHNOLOGY, force=force))
        except Exception as exc:
            logger.exception("SON ML failed for %s", vendor)
            results.append({"vendor": vendor, "rat": cfg.TECHNOLOGY, "error": str(exc), "skipped": False})
    try:
        treat = train_treatment()
        results.append({"vendor": "all", "rat": cfg.TECHNOLOGY, "treatment": treat, "skipped": False})
    except Exception as exc:
        logger.exception("SON ML treatment training failed")
        results.append({"vendor": "all", "error": str(exc), "step": "treatment"})
    return results
