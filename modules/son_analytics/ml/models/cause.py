"""Root-cause classifier from weak detector labels."""

from __future__ import annotations

import logging

import numpy as np

from .. import config as cfg
from ..labels import heuristic_cause_probs

logger = logging.getLogger(__name__)


def fit_cause(x: np.ndarray, rows: list[dict], weak: dict[str, dict[str, float]]) -> list[dict]:
    y = np.zeros((len(rows), len(cfg.CAUSE_LABELS)), dtype=float)
    labeled = 0
    for i, row in enumerate(rows):
        key = str(row.get("cell_name") or "").strip().lower()
        labs = weak.get(key)
        if labs:
            labeled += 1
            for j, name in enumerate(cfg.CAUSE_LABELS):
                y[i, j] = float(labs.get(name) or 0.0)

    usable = [j for j in range(y.shape[1]) if float(y[:, j].sum()) >= 2]
    if labeled < 20 or x.shape[0] < 20 or len(usable) < 2:
        return [heuristic_cause_probs(row) for row in rows]

    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.multiclass import OneVsRestClassifier
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return [heuristic_cause_probs(row) for row in rows]

    xs = StandardScaler().fit_transform(x)
    y_fit = y[:, usable]
    names_fit = [cfg.CAUSE_LABELS[j] for j in usable]
    clf = OneVsRestClassifier(
        LogisticRegression(max_iter=400, class_weight="balanced", solver="liblinear"),
    )
    try:
        clf.fit(xs, y_fit)
        proba = clf.predict_proba(xs)
    except Exception:
        logger.exception("Cause classifier training failed; using heuristic")
        return [heuristic_cause_probs(row) for row in rows]

    if isinstance(proba, list):
        cols = []
        for p in proba:
            if p.ndim == 2 and p.shape[1] == 2:
                cols.append(p[:, 1])
            else:
                cols.append(np.asarray(p).reshape(-1))
        proba = np.column_stack(cols)

    out: list[dict] = []
    for i in range(len(rows)):
        raw = {name: 0.0 for name in cfg.CAUSE_LABELS}
        for j, name in enumerate(names_fit):
            raw[name] = float(proba[i, j]) if j < proba.shape[1] else 0.0
        total = sum(raw.values()) or 1.0
        blended = heuristic_cause_probs(rows[i])
        merged = {k: round(0.7 * raw.get(k, 0) / total + 0.3 * blended.get(k, 0), 4) for k in cfg.CAUSE_LABELS}
        out.append(merged)
    return out
