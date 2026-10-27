"""Cross-sectional and interval metrics (README Phase 4 / section 12).

All functions take plain arrays for ONE cross-section (one budget, or one budget x sector) unless noted, and
return NaN when the metric is undefined (for example Spearman IC of a constant score).
"""

from __future__ import annotations

import numpy as np
from scipy.stats import rankdata, spearmanr


def _clean(pred: np.ndarray, actual: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pred, actual = np.asarray(pred, dtype=float), np.asarray(actual, dtype=float)
    ok = ~np.isnan(pred) & ~np.isnan(actual)
    return pred[ok], actual[ok]


def spearman_ic(pred: np.ndarray, actual: np.ndarray) -> float:
    """Spearman rank correlation of predicted vs realised excess return (NaN if either side is constant)."""
    pred, actual = _clean(pred, actual)
    if len(pred) < 3 or np.ptp(pred) == 0 or np.ptp(actual) == 0:
        return float("nan")
    return float(spearmanr(pred, actual).statistic)


def top_k_hit_rate(pred: np.ndarray, actual: np.ndarray, k: int = 3) -> float:
    """Share of the predicted top-k that are also in the realised top-k (1.0 = perfect, k/n = chance)."""
    pred, actual = _clean(pred, actual)
    if len(pred) < k or np.ptp(pred) == 0:
        return float("nan")
    top_pred = set(np.argsort(-pred, kind="stable")[:k])
    top_actual = set(np.argsort(-actual, kind="stable")[:k])
    return len(top_pred & top_actual) / k


def mae(pred: np.ndarray, actual: np.ndarray) -> float:
    pred, actual = _clean(pred, actual)
    return float(np.mean(np.abs(pred - actual))) if len(pred) else float("nan")


def directional_accuracy(pred: np.ndarray, actual: np.ndarray) -> float:
    """Share of rows where the sign of the predicted excess return equals the sign of the realised one."""
    pred, actual = _clean(pred, actual)
    if not len(pred):
        return float("nan")
    return float(np.mean(np.sign(pred) == np.sign(actual)))


def precision_at_k(pred: np.ndarray, actual: np.ndarray, k: int = 5) -> float:
    """Of the predicted top-k, the share that beat the cross-section's median realised excess return."""
    pred, actual = _clean(pred, actual)
    if len(pred) <= k or np.ptp(pred) == 0:
        return float("nan")
    top = np.argsort(-pred, kind="stable")[:k]
    return float(np.mean(actual[top] > np.median(actual)))


def ndcg_at_k(pred: np.ndarray, actual: np.ndarray, k: int = 10) -> float:
    """NDCG@k with relevance = rank of the realised return (worst = 0 ... best = n-1)."""
    pred, actual = _clean(pred, actual)
    n = len(pred)
    if n < 2 or np.ptp(pred) == 0:
        return float("nan")
    k = min(k, n)
    relevance = rankdata(actual, method="average") - 1.0
    discounts = 1.0 / np.log2(np.arange(2, k + 2))
    order = np.argsort(-pred, kind="stable")[:k]
    ideal = np.sort(relevance)[::-1][:k]
    dcg = float(np.sum(relevance[order] * discounts))
    idcg = float(np.sum(ideal * discounts))
    return dcg / idcg if idcg > 0 else float("nan")


def interval_coverage(lo: np.ndarray, hi: np.ndarray, actual: np.ndarray) -> float:
    lo, hi, actual = (np.asarray(a, dtype=float) for a in (lo, hi, actual))
    ok = ~np.isnan(lo) & ~np.isnan(hi) & ~np.isnan(actual)
    if not ok.any():
        return float("nan")
    return float(np.mean((actual[ok] >= lo[ok]) & (actual[ok] <= hi[ok])))


def interval_width(lo: np.ndarray, hi: np.ndarray) -> float:
    lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    ok = ~np.isnan(lo) & ~np.isnan(hi)
    return float(np.mean(hi[ok] - lo[ok])) if ok.any() else float("nan")
