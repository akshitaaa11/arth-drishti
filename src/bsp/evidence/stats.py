"""Small statistics helpers for the Phase 8 evidence: year-level bootstrap, t-tests and Benjamini-Hochberg."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

N_BOOT = 10_000


@dataclass(frozen=True)
class Summary:
    n: int
    mean: float
    lo: float
    hi: float
    t_stat: float
    p_two_sided: float
    p_one_sided_positive: float


def summarise(values: np.ndarray | list[float], seed: int = 42, level: float = 0.95, n_boot: int = N_BOOT) -> Summary:
    """Mean, percentile-bootstrap CI (resampling the values, i.e. test years) and a one-sample t-test against 0."""
    x = np.asarray([v for v in values if not math.isnan(v)], dtype=float)
    n = len(x)
    if n < 2:
        return Summary(n, float(x.mean()) if n else float("nan"), float("nan"), float("nan"), float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    draws = rng.choice(x, size=(n_boot, n), replace=True).mean(axis=1)
    tail = (1 - level) / 2
    lo, hi = np.quantile(draws, [tail, 1 - tail])
    sd = float(x.std(ddof=1))
    t = float(x.mean() / (sd / math.sqrt(n))) if sd > 0 else float("nan")
    p_two = float(2 * stats.t.sf(abs(t), n - 1)) if not math.isnan(t) else float("nan")
    p_pos = float(stats.t.sf(t, n - 1)) if not math.isnan(t) else float("nan")
    return Summary(n, float(x.mean()), float(lo), float(hi), t, p_two, p_pos)


def paired_difference(a: np.ndarray | list[float], b: np.ndarray | list[float], seed: int = 42) -> Summary:
    """Summary of a - b over matched years (rows with a missing value in either are dropped)."""
    xa, xb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    keep = ~np.isnan(xa) & ~np.isnan(xb)
    return summarise(xa[keep] - xb[keep], seed=seed)


def benjamini_hochberg(p_values: list[float] | np.ndarray) -> np.ndarray:
    """BH adjusted p-values (q-values); NaN p-values stay NaN and do not count as tests."""
    p = np.asarray(p_values, dtype=float)
    q = np.full(p.shape, np.nan)
    ok = ~np.isnan(p)
    m = int(ok.sum())
    if m == 0:
        return q
    order = np.argsort(p[ok])
    ranked = p[ok][order] * m / np.arange(1, m + 1)
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(adjusted, 1.0)
    q[ok] = out
    return q
