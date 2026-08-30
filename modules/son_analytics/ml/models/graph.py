"""Neighbor-graph scores: numpy always, optional torch GraphSAGE-style update."""

from __future__ import annotations

import numpy as np

from .. import config as cfg


def _numpy_graph_scores(
    rows: list[dict],
    embeddings: list[list[float]],
    adjacency: dict[str, list[str]],
) -> list[float]:
    index = {str(r.get("cell_name") or "").strip().lower(): i for i, r in enumerate(rows)}
    emb = np.asarray(embeddings, dtype=float)
    if emb.ndim != 2 or emb.shape[0] != len(rows):
        return [0.0] * len(rows)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms < 1e-9] = 1.0
    unit = emb / norms
    scores = []
    for i, row in enumerate(rows):
        key = str(row.get("cell_name") or "").strip().lower()
        neigh = [index[n] for n in adjacency.get(key, []) if n in index]
        nbr_pen = float(row.get("nbr_missing_recip") or 0) * 40.0
        dist_pen = 15.0 if float(row.get("nbr_distance_km") or 0) >= 12 else 0.0
        ho_pen = 25.0 if 0 < float(row.get("nbr_ho_sr") or 100) < 95 else 0.0
        if neigh:
            mean_n = unit[neigh].mean(axis=0)
            mean_n = mean_n / (np.linalg.norm(mean_n) + 1e-9)
            isol = float(1.0 - np.clip(np.dot(unit[i], mean_n), -1.0, 1.0)) * 50.0
        else:
            isol = 10.0
        scores.append(float(min(100.0, isol + nbr_pen + dist_pen + ho_pen)))
    return scores


def _torch_sage_scores(
    rows: list[dict],
    embeddings: list[list[float]],
    adjacency: dict[str, list[str]],
) -> list[float] | None:
    if not cfg.torch_enabled():
        return None
    try:
        import torch
        from torch import nn
    except ImportError:
        return None
    if len(rows) < 16:
        return None

    emb = torch.tensor(embeddings, dtype=torch.float32)
    n, d = emb.shape
    index = {str(r.get("cell_name") or "").strip().lower(): i for i, r in enumerate(rows)}
    neigh_mean = torch.zeros_like(emb)
    for i, row in enumerate(rows):
        key = str(row.get("cell_name") or "").strip().lower()
        idxs = [index[n] for n in adjacency.get(key, []) if n in index]
        if idxs:
            neigh_mean[i] = emb[idxs].mean(dim=0)

    class Sage(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lin = nn.Linear(d * 2, d)

        def forward(self, h, mean_n):
            return torch.relu(self.lin(torch.cat([h, mean_n], dim=1)))

    model = Sage()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    # Unsupervised: reconstruct self embedding from neighbor mean (homophily).
    for _ in range(12):
        h1 = model(emb, neigh_mean)
        loss = nn.functional.mse_loss(h1, emb)
        opt.zero_grad()
        loss.backward()
        opt.step()
    with torch.no_grad():
        h1 = model(emb, neigh_mean)
        residual = ((h1 - emb) ** 2).mean(dim=1).numpy()
    lo, hi = float(residual.min()), float(residual.max())
    if hi - lo < 1e-9:
        scaled = np.zeros_like(residual)
    else:
        scaled = (residual - lo) / (hi - lo) * 100.0
    base = _numpy_graph_scores(rows, embeddings, adjacency)
    return [float(min(100.0, 0.6 * s + 0.4 * b)) for s, b in zip(scaled.tolist(), base)]


def graph_scores(
    rows: list[dict],
    embeddings: list[list[float]],
    adjacency: dict[str, list[str]],
) -> list[float]:
    torch_scores = _torch_sage_scores(rows, embeddings, adjacency)
    if torch_scores is not None:
        return torch_scores
    return _numpy_graph_scores(rows, embeddings, adjacency)
