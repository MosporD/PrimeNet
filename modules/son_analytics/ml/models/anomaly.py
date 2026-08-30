"""PCA embeddings + IsolationForest (+ optional torch autoencoder)."""

from __future__ import annotations

import logging
import math

import numpy as np

from .. import config as cfg

logger = logging.getLogger(__name__)


def _minmax_01(values: np.ndarray) -> np.ndarray:
    lo = float(np.min(values))
    hi = float(np.max(values))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi - lo < 1e-9:
        return np.zeros_like(values, dtype=float)
    return (values - lo) / (hi - lo)


def _try_autoencoder(x: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
    if not cfg.torch_enabled() or x.shape[0] < 16:
        return None, None
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        return None, None

    n_in = int(x.shape[1])
    bottleneck = min(cfg.AE_BOTTLENECK, max(2, n_in // 2))

    class TinyAE(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            hidden = min(cfg.AE_HIDDEN, max(8, n_in * 2))
            self.enc = nn.Sequential(nn.Linear(n_in, hidden), nn.ReLU(), nn.Linear(hidden, bottleneck))
            self.dec = nn.Sequential(nn.Linear(bottleneck, hidden), nn.ReLU(), nn.Linear(hidden, n_in))

        def forward(self, inp):
            z = self.enc(inp)
            return self.dec(z), z

    model = TinyAE()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    tensor = torch.tensor(x, dtype=torch.float32)
    loader = DataLoader(TensorDataset(tensor), batch_size=min(256, max(8, x.shape[0])), shuffle=True)
    model.train()
    for _ in range(cfg.AE_EPOCHS):
        for (batch,) in loader:
            recon, _z = model(batch)
            loss = nn.functional.mse_loss(recon, batch)
            opt.zero_grad()
            loss.backward()
            opt.step()
    model.eval()
    with torch.no_grad():
        recon, z = model(tensor)
        residual = ((recon - tensor) ** 2).mean(dim=1).numpy()
        emb = z.numpy()
    return residual, emb


def fit_anomaly(x: np.ndarray, feature_names: list[str]) -> dict:
    """Return per-row anomaly_score (0-100), embedding, top_kpis, model_name, fallback_used."""
    from sklearn.decomposition import PCA
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    if x.shape[0] < 8:
        n = int(x.shape[0])
        zeros = [[0.0] * min(cfg.EMBEDDING_DIM, max(1, x.shape[1])) for _ in range(n)]
        return {
            "anomaly_score": [0.0] * n,
            "embedding": zeros,
            "top_kpis": [[] for _ in range(n)],
            "model_name": "skipped",
            "fallback_used": True,
        }

    scaler = StandardScaler()
    xs = scaler.fit_transform(x)
    n_comp = min(cfg.EMBEDDING_DIM, xs.shape[1], max(1, xs.shape[0] - 1))
    pca = PCA(n_components=n_comp, random_state=42)
    pca_emb = pca.fit_transform(xs)

    if_model = IsolationForest(
        n_estimators=cfg.IF_ESTIMATORS,
        contamination=cfg.IF_CONTAMINATION,
        random_state=42,
        n_jobs=1,
    )
    if_model.fit(xs)
    if_raw = -if_model.decision_function(xs)
    if_score = _minmax_01(if_raw) * 100.0

    ae_residual, ae_emb = _try_autoencoder(xs)
    fallback = ae_residual is None
    if ae_residual is not None:
        ae_score = _minmax_01(ae_residual) * 100.0
        blended = 0.55 * if_score + 0.45 * ae_score
        embedding = ae_emb if ae_emb is not None else pca_emb
        model_name = "iforest+autoencoder"
        contrib = np.abs(xs)
    else:
        blended = if_score
        embedding = pca_emb
        model_name = "iforest+pca"
        contrib = np.abs(xs)

    top_kpis: list[list[dict]] = []
    n_feat = min(len(feature_names), contrib.shape[1])
    for i in range(contrib.shape[0]):
        order = np.argsort(contrib[i, :n_feat])[::-1]
        items = []
        for idx in order[:3]:
            items.append({
                "kpi": feature_names[int(idx)],
                "contribution": round(float(contrib[i, int(idx)]), 3),
            })
        top_kpis.append(items)

    return {
        "anomaly_score": blended.tolist(),
        "embedding": embedding.tolist(),
        "top_kpis": top_kpis,
        "model_name": model_name,
        "fallback_used": fallback,
    }
