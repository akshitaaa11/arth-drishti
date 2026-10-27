"""Combining Tier-1 models, and the Tier-2 stock-ranking helpers that sit on top of the sector output."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import rankdata

KEYS = ["budget_id", "entity"]


def rank_percentile(values: np.ndarray) -> np.ndarray:
    """Rank of each value within the group as a share in (0, 1]; higher value = higher share."""
    return rankdata(values, method="average") / len(values)


def blend_predictions(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Equal-weight blend of out-of-sample sector predictions from several models (same folds, same rows).

    ``score`` is the mean of each model's within-budget rank percentile; ``expected``, ``p_beat``, ``lo`` and ``hi`` are
    the means of the components'. Weights are equal on purpose: learning stacking weights from ~12 test years would be
    noisier than equal weights, and any weights fitted on out-of-sample results would leak the test years into the blend.
    """
    names = list(frames)
    base = frames[names[0]][[*KEYS, "sector_id", "is_control", "actual"]].copy()
    merged = base
    for name, frame in frames.items():
        part = frame[[*KEYS, "score", "expected", "p_beat", "lo", "hi"]].copy()
        part["pct"] = part.groupby("budget_id")["score"].transform(lambda s: rank_percentile(s.to_numpy()))
        part = part.drop(columns="score").rename(columns={c: f"{c}__{name}" for c in ("expected", "p_beat", "lo", "hi", "pct")})
        merged = merged.merge(part, on=KEYS, how="inner", validate="one_to_one")
    out = merged[[*KEYS, "sector_id", "is_control", "actual"]].copy()
    out["score"] = merged[[f"pct__{n}" for n in names]].mean(axis=1)
    for column in ("expected", "p_beat", "lo", "hi"):
        out[column] = merged[[f"{column}__{n}" for n in names]].mean(axis=1)
    return out


def tier1_features(blend: pd.DataFrame) -> pd.DataFrame:
    """Out-of-sample Tier-1 outputs per sector and budget, to be joined onto the stock rows."""
    return blend[["budget_id", "entity", "score", "expected", "p_beat"]].rename(
        columns={"score": "t1_rank_score", "expected": "t1_expected", "p_beat": "t1_p_beat"})


class SectorThenMomentum:
    """Control for Tier 2: rank stocks by their sector's Tier-1 rank, ties broken by 12m momentum.

    If the stock ranker does not beat this, picking stocks inside the chosen sectors adds nothing over the sector call."""

    selects_all = False

    def fit(self, train: pd.DataFrame, features: list[str]) -> SectorThenMomentum:
        return self

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        momentum = test["momentum_12m"].astype(float)
        tie = momentum.groupby(test["sector_id"].to_numpy()).rank(pct=True).fillna(0.5).to_numpy()
        return pd.DataFrame({"score": test["t1_rank_score"].to_numpy(dtype=float) + 1e-3 * tie})


def learned_stack(frames: dict[str, pd.DataFrame], budgets: pd.DataFrame, grid: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0),
                  min_folds: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stacked ensemble of exactly two models with a weight learned only from earlier out-of-sample folds.

    For test budget t the weight w on the first model (1 - w on the second) is the grid value with the highest mean Spearman IC
    over the earlier folds whose 12m label was already resolved on t's day 0 (``label_end <= day0(t)``); with fewer than
    ``min_folds`` such folds the weight is 0.5. ``budgets`` has columns ``budget_id``, ``presented_on``, ``day0``, ``label_end``.
    Returns (predictions in the same format as ``blend_predictions``, the weight used per budget).
    """
    from bsp.evaluation import metrics

    first, second = list(frames)
    parts = {name: blend_predictions({name: frame}) for name, frame in frames.items()}  # per-model percentile frames
    meta = budgets.set_index("budget_id")
    pct = {n: p.set_index(KEYS)["score"] for n, p in parts.items()}
    raw = {n: f.set_index(KEYS) for n, f in frames.items()}
    ordered = sorted(frames[first]["budget_id"].unique(), key=lambda b: meta.loc[b, "presented_on"])
    pieces, weights = [], []
    for budget in ordered:
        past = [b for b in ordered if meta.loc[b, "presented_on"] < meta.loc[budget, "presented_on"]
                and meta.loc[b, "label_end"] <= meta.loc[budget, "day0"]]
        weight = 0.5
        if len(past) >= min_folds:
            best = -np.inf
            for w in grid:
                ics = []
                for b in past:
                    g = parts[first][parts[first]["budget_id"] == b]
                    g = g[~g["is_control"]]
                    keys = list(zip(g["budget_id"], g["entity"], strict=True))
                    s = w * pct[first].loc[keys].to_numpy() + (1 - w) * pct[second].loc[keys].to_numpy()
                    ic = metrics.spearman_ic(s, g["actual"].to_numpy())
                    if not np.isnan(ic):
                        ics.append(ic)
                value = float(np.mean(ics)) if ics else -np.inf
                if value > best + 1e-12:  # ties keep the smaller w, i.e. the earlier grid value: deterministic
                    best, weight = value, w
        weights.append({"budget_id": budget, "weight_first": weight, "n_past_folds": len(past), "first": first, "second": second})
        g = parts[first][parts[first]["budget_id"] == budget].copy()
        index = list(zip(g["budget_id"], g["entity"], strict=True))
        g["score"] = weight * pct[first].loc[index].to_numpy() + (1 - weight) * pct[second].loc[index].to_numpy()
        for column in ("expected", "p_beat", "lo", "hi"):
            a = raw[first][column].loc[index].to_numpy(dtype=float)
            b = raw[second][column].loc[index].to_numpy(dtype=float)
            g[column] = weight * a + (1 - weight) * b
        pieces.append(g)
    return pd.concat(pieces, ignore_index=True), pd.DataFrame(weights)
