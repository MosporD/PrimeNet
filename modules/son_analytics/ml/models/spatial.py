"""Spatial clustering on embeddings + lat/lon (Phase 4)."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from .. import config as cfg


def cluster_spatial(rows: list[dict], embeddings: list[list[float]]) -> list[dict]:
    """Return per-row {spatial_cluster_id, spatial_coherence}."""
    n = len(rows)
    empty = [{"spatial_cluster_id": "", "spatial_coherence": ""} for _ in range(n)]
    if n < cfg.SPATIAL_MIN_SAMPLES:
        return empty

    coords = []
    keep = []
    for i, row in enumerate(rows):
        lat, lng = row.get("latitude"), row.get("longitude")
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except (TypeError, ValueError):
            continue
        if lat_f == 0 and lng_f == 0:
            continue
        coords.append((lat_f, lng_f, i))
        keep.append(i)
    if len(keep) < cfg.SPATIAL_MIN_SAMPLES:
        return empty

    from sklearn.cluster import DBSCAN
    from sklearn.preprocessing import StandardScaler

    geo = np.array([[c[0], c[1]] for c in coords], dtype=float)
    emb_dim = 0
    if embeddings and embeddings[0]:
        emb_dim = min(4, len(embeddings[0]))
    if emb_dim:
        extra = np.array([embeddings[i][:emb_dim] for i in keep], dtype=float)
        feat = np.hstack([geo, extra])
    else:
        feat = geo
    xs = StandardScaler().fit_transform(feat)
    labels = DBSCAN(eps=0.8, min_samples=cfg.SPATIAL_MIN_SAMPLES).fit_predict(xs)

    members: dict[int, list[int]] = defaultdict(list)
    for local_i, lab in enumerate(labels):
        if int(lab) >= 0:
            members[int(lab)].append(keep[local_i])

    out = [dict(item) for item in empty]
    for lab, idxs in members.items():
        sites = {str(rows[i].get("site_id") or "") for i in idxs if rows[i].get("site_id")}
        areas = {str(rows[i].get("area") or "") for i in idxs if rows[i].get("area")}
        lats = [float(rows[i]["latitude"]) for i in idxs if rows[i].get("latitude") is not None]
        lngs = [float(rows[i]["longitude"]) for i in idxs if rows[i].get("longitude") is not None]
        span = 0.0
        if lats and lngs:
            span = max(max(lats) - min(lats), max(lngs) - min(lngs))
        if len(sites) <= 1:
            coherence = "site"
        elif span < 0.04:
            coherence = "local"
        elif len(areas) == 1:
            coherence = "corridor"
        else:
            coherence = "area-wide"
        cid = f"sp-{lab}"
        for i in idxs:
            out[i] = {"spatial_cluster_id": cid, "spatial_coherence": coherence}
    return out
