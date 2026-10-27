"""Bayesian hierarchical regression in PyMC (README Phase 5, Tier 1).

    y[s, t] = a[s] + b[s] * surprise[s, t] + c . controls[s, t] + noise,   noise ~ Normal(0, sigma)
    a[s] = mu_a + tau_a * za[s]        (sector intercepts, partially pooled)
    b[s] = mu_b + tau_b * zb[s]        (sector-specific slopes on the budget surprise, partially pooled)

``y`` is the 12m excess return of sector s after budget t, ``surprise`` is ``alloc_vs_prev_re_pct`` (new BE against last
year's RE) and the controls (pooled slopes) are 12m momentum and execution credibility. All predictors are standardised
with training statistics only; a missing predictor is replaced by the training median, i.e. 0 after standardising
(documented imputation; no row is dropped). The non-centred form keeps the sampler stable with 12-15 groups.

Predictions are the posterior predictive of the new row: ``expected`` = its mean, ``lo`` / ``hi`` = the 10% / 90%
quantiles (an 80% credible interval), ``p_beat`` = P(excess return > 0), ``score`` = ``expected``.
The sampler's health (max R-hat, divergences, minimum bulk ESS) is kept in ``diagnostics`` for the report.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pymc as pm

SURPRISE = "alloc_vs_prev_re_pct"
CONTROLS = ["momentum_12m", "credibility_pct"]


class BayesHierarchical:
    selects_all = False

    def __init__(self, seed: int = 42, draws: int = 500, tune: int = 500, chains: int = 2,
                 target_accept: float = 0.95, interval_level: float = 0.8) -> None:
        self.seed, self.draws, self.tune, self.chains = seed, draws, tune, chains
        self.target_accept, self.interval_level = target_accept, interval_level
        self.sectors: list[str] = []
        self.columns: list[str] = []
        self.stats: pd.DataFrame | None = None
        self.y_mean = self.y_std = 0.0
        self.post: dict[str, np.ndarray] = {}
        self.diagnostics: dict[str, float] = {}

    def _design(self, frame: pd.DataFrame) -> np.ndarray:
        assert self.stats is not None
        x = frame[self.columns].astype(float).fillna(self.stats["median"])
        return ((x - self.stats["mean"]) / self.stats["std"]).to_numpy()

    def fit(self, train: pd.DataFrame, features: list[str]) -> BayesHierarchical:
        self.columns = [c for c in [SURPRISE, *CONTROLS] if c in train.columns]
        x = train[self.columns].astype(float)
        med = x.median()
        filled = x.fillna(med)
        self.stats = pd.DataFrame({"median": med, "mean": filled.mean(), "std": filled.std(ddof=0).replace(0, 1.0)})
        self.sectors = sorted(train["entity"].unique())
        sector_index = train["entity"].map({s: i for i, s in enumerate(self.sectors)}).to_numpy()
        design = self._design(train)
        y = train["excess_return"].to_numpy(dtype=float)
        self.y_mean, self.y_std = float(y.mean()), float(y.std(ddof=0)) or 1.0
        yz = (y - self.y_mean) / self.y_std
        n_sectors, n_controls = len(self.sectors), len(self.columns) - 1
        logging.getLogger("pymc").setLevel(logging.ERROR)
        with pm.Model():
            mu_a = pm.Normal("mu_a", 0.0, 1.0)
            tau_a = pm.HalfNormal("tau_a", 0.5)
            za = pm.Normal("za", 0.0, 1.0, shape=n_sectors)
            mu_b = pm.Normal("mu_b", 0.0, 0.5)
            tau_b = pm.HalfNormal("tau_b", 0.5)
            zb = pm.Normal("zb", 0.0, 1.0, shape=n_sectors)
            a = pm.Deterministic("a", mu_a + tau_a * za)
            b = pm.Deterministic("b", mu_b + tau_b * zb)
            mean = a[sector_index] + b[sector_index] * design[:, 0]
            if n_controls:
                c = pm.Normal("c", 0.0, 0.5, shape=n_controls)
                mean = mean + pm.math.dot(design[:, 1:], c)
            sigma = pm.HalfNormal("sigma", 1.0)
            pm.Normal("y", mean, sigma, observed=yz)
            idata = pm.sample(self.draws, tune=self.tune, chains=self.chains, cores=1, random_seed=self.seed,
                              target_accept=self.target_accept, progressbar=False, compute_convergence_checks=False)
        post = idata.posterior
        stack = lambda name: post[name].stack(sample=("chain", "draw")).transpose("sample", ...).to_numpy()  # noqa: E731
        self.post = {name: stack(name) for name in ("a", "b", "sigma")}
        if n_controls:
            self.post["c"] = stack("c")
        self.diagnostics = _diagnostics(idata)
        return self

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        design = self._design(test)
        index = test["entity"].map({s: i for i, s in enumerate(self.sectors)}).to_numpy()
        if np.isnan(index.astype(float)).any():
            raise ValueError("a test sector was not in the training rows")
        index = index.astype(int)
        mean = self.post["a"][:, index] + self.post["b"][:, index] * design[:, 0]
        if "c" in self.post:
            mean = mean + self.post["c"] @ design[:, 1:].T
        rng = np.random.default_rng(self.seed)
        draws = mean + rng.standard_normal(mean.shape) * self.post["sigma"][:, None]
        draws = draws * self.y_std + self.y_mean
        tail = (1 - self.interval_level) / 2
        expected = draws.mean(axis=0)
        return pd.DataFrame({
            "score": expected, "expected": expected, "p_beat": (draws > 0).mean(axis=0),
            "lo": np.quantile(draws, tail, axis=0), "hi": np.quantile(draws, 1 - tail, axis=0),
        })

    def slopes(self) -> pd.DataFrame:
        """Posterior mean and 80% interval of each sector's surprise slope (in standardised units)."""
        b = self.post["b"]
        return pd.DataFrame({"sector": self.sectors, "slope_mean": b.mean(axis=0),
                             "slope_lo": np.quantile(b, 0.1, axis=0), "slope_hi": np.quantile(b, 0.9, axis=0)})


def _diagnostics(idata: Any) -> dict[str, float]:
    import arviz as az

    summary = az.summary(idata, var_names=["mu_a", "tau_a", "mu_b", "tau_b", "sigma"], kind="diagnostics")
    divergent = int(idata.sample_stats["diverging"].sum())
    return {"max_rhat": float(summary["r_hat"].max()), "min_ess_bulk": float(summary["ess_bulk"].min()),
            "divergences": float(divergent)}
