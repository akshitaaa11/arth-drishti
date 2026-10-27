"""F11 causal check: difference-in-differences, large-surprise sectors against matched sectors, around each budget.

Per full budget FY2005-06 to FY2023-24 (hold-out and live year excluded; interim budgets have no surprise data):
  treated  = the 4 sectors with the largest allocation surprise (``alloc_vs_prev_re_pct``) among the budget-sensitive sectors;
  controls = sectors NOT treated whose surprise is at or below the median, each treated sector matched (without replacement) to the
             control nearest in standardised pre-budget 12m momentum and 90d volatility (both known on budget day);
  outcome  = a sector basket's daily return minus the Nifty 500's, summed over a window of trading days;
  DiD      = (post - pre) of the treated sector minus (post - pre) of its matched control, pre = days -60..-1, post = days +1..+60
             (and +1..+120); day 0 is the first trading day on or after the budget, so the reaction day itself is left out.
Parallel-trends check: the same difference with pre = days -120..-61 and "post" = days -60..-1 should be near 0.
Inference: the budgets are the independent units (one DiD per budget): mean, bootstrap CI and t-test over budgets, plus a permutation
test that shuffles the surprise labels across sectors within each budget (2,000 shuffles, seeded) and repeats the whole procedure.
A positive DiD means large-surprise sectors did better after the budget than their look-alikes did, relative to before.
This is evidence of association under matching on two observables, not proof of causation; with 19 budgets it is weak either way.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bsp.evidence.context import Context
from bsp.evidence.stats import summarise

N_TREATED = 4
PRE, POST_WINDOWS = 60, (60, 120)
N_PERM = 2000
MIN_COVERAGE = 0.8


def _window_sum(excess: pd.DataFrame, lo: int, hi: int) -> pd.Series:
    """Sum of the daily excess returns over positions lo..hi-1 per sector; NaN if less than 80% of the days exist."""
    block = excess.iloc[lo:hi]
    return block.sum(skipna=True).where(block.notna().mean() >= MIN_COVERAGE)


def _match(surprise: pd.Series, momentum: pd.Series, volatility: pd.Series) -> list[tuple[str, str]]:
    avail = surprise.dropna()
    if len(avail) < 10:
        return []
    treated = list(avail.sort_values(ascending=False, kind="mergesort").index[:N_TREATED])
    pool = [s for s in avail.index if s not in treated and avail[s] <= avail.median()]
    z_m = (momentum - momentum.mean()) / (momentum.std(ddof=0) or 1.0)
    z_v = (volatility - volatility.mean()) / (volatility.std(ddof=0) or 1.0)
    pairs: list[tuple[str, str]] = []
    for t in treated:
        candidates = [c for c in pool if c not in {p[1] for p in pairs}]
        if not candidates:
            break
        dist = {c: np.nansum([(z_m[t] - z_m[c]) ** 2, (z_v[t] - z_v[c]) ** 2]) for c in candidates}
        pairs.append((t, min(sorted(dist), key=lambda c: dist[c])))
    return pairs


def _did(pairs: list[tuple[str, str]], before: pd.Series, after: pd.Series) -> float:
    diffs = [(after[t] - before[t]) - (after[c] - before[c]) for t, c in pairs]
    diffs = [d for d in diffs if not np.isnan(d)]
    return float(np.mean(diffs)) if diffs else float("nan")


def run_did(ctx: Context, n_perm: int = N_PERM, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    bundle, frame = ctx.bundle, ctx.panel.frame
    excess = bundle.sector_returns.sub(bundle.market_returns, axis=0)
    days = list(excess.index.astype(str))
    sensitive = [s for s in frame["entity"].unique() if not bool(frame.loc[frame["entity"] == s, "is_control"].iloc[0])]
    calendar = ctx.calendar.set_index("budget_id")
    budgets: list[tuple[str, pd.Series, pd.Series, pd.Series, dict[str, pd.Series]]] = []
    for budget_id, g in frame.groupby("budget_id", sort=False):
        i0 = days.index(str(calendar["day0"][str(budget_id)]))
        if i0 < 2 * PRE or i0 + max(POST_WINDOWS) >= len(days):
            continue
        g = g[g["entity"].isin(sensitive)].set_index("entity")
        windows = {
            "prev": _window_sum(excess, i0 - 2 * PRE, i0 - PRE), "pre": _window_sum(excess, i0 - PRE, i0),
            **{f"post{w}": _window_sum(excess, i0 + 1, i0 + 1 + w) for w in POST_WINDOWS}}
        budgets.append((str(budget_id), g["alloc_vs_prev_re_pct"].astype(float), g["momentum_12m"].astype(float),
                        g["volatility_90d"].astype(float), windows))
    rows = []
    for budget_id, surprise, momentum, volatility, win in budgets:
        pairs = _match(surprise, momentum, volatility)
        if not pairs:
            continue
        rows.append({"budget_id": budget_id, "n_pairs": len(pairs), "treated": ",".join(t for t, _ in pairs), "controls": ",".join(c for _, c in pairs),
                     "pretrend_did": _did(pairs, win["prev"], win["pre"]),
                     **{f"did_post{w}": _did(pairs, win["pre"], win[f"post{w}"]) for w in POST_WINDOWS}})
    by_budget = pd.DataFrame(rows)
    rng = np.random.default_rng(seed)
    summary = []
    for column in ["pretrend_did", *[f"did_post{w}" for w in POST_WINDOWS]]:
        s = summarise(by_budget[column].to_numpy())
        before_key, after_key = ("prev", "pre") if column == "pretrend_did" else ("pre", column.replace("did_", ""))
        perm = []
        for _ in range(n_perm):
            vals = []
            for _, surprise, momentum, volatility, win in budgets:
                shuffled = pd.Series(rng.permutation(surprise.to_numpy()), index=surprise.index)
                pairs = _match(shuffled, momentum, volatility)
                if pairs:
                    vals.append(_did(pairs, win[before_key], win[after_key]))
            perm.append(float(np.nanmean(vals)))
        p_perm = float((np.sum(np.abs(perm) >= abs(s.mean)) + 1) / (len(perm) + 1))
        summary.append({"measure": column, "n_budgets": s.n, "mean_did": s.mean, "ci_lo": s.lo, "ci_hi": s.hi, "t_stat": s.t_stat,
                        "p_t_test": s.p_two_sided, "p_permutation": p_perm, "share_budgets_positive": float((by_budget[column] > 0).mean())})
    return by_budget, pd.DataFrame(summary)
