"""Do budgets move sectors? Sector event effects with Benjamini-Hochberg correction across the 15 sectors (README Phase 8).

For each event window of data/csv/event_study.csv and each sector, the cumulative abnormal returns (market model, Phase 3) of the
full budgets FY2005-06 to FY2023-24 are averaged and tested against 0 with a one-sample t-test across budgets (one number per
budget, so the budgets are the independent units). The 15 p-values of a window are adjusted with Benjamini-Hochberg; a second
adjustment pools all 75 tests (not necessarily stricter: it depends on how the p-values are spread). Interim budgets and the locked hold-out / live years are excluded. IT Services is the
control sector: a significant effect there would be a warning, not a finding.
"""

from __future__ import annotations

import pandas as pd

from bsp.evaluation.config import EvalConfig
from bsp.evidence.stats import benjamini_hochberg, summarise

ALPHA = 0.05


def sector_event_effects(cfg: EvalConfig) -> pd.DataFrame:
    events = pd.read_csv(cfg.root / "config" / "budget_events.csv")
    keep = events[(events["budget_type"] == "full") & (~events["fiscal_year"].astype(str).isin(cfg.locked_fiscal_years))]["budget_id"]
    study = pd.read_csv(cfg.root / "data" / "csv" / "event_study.csv")
    study = study[(study["entity_type"] == "sector") & (study["budget_id"].isin(set(keep)))]
    rows = []
    for (window, sector), g in study.groupby(["window", "entity"], sort=False):
        s = summarise(g["car"].to_numpy())
        rows.append({"window": window, "sector": sector, "n_budgets": s.n, "mean_car": s.mean, "ci_lo": s.lo, "ci_hi": s.hi,
                     "t_stat": s.t_stat, "p_value": s.p_two_sided,
                     "share_positive": float((g["car"] > 0).mean())})
    frame = pd.DataFrame(rows)
    frame["q_within_window"] = frame.groupby("window")["p_value"].transform(lambda p: benjamini_hochberg(p.to_numpy()))
    frame["q_all_75_tests"] = benjamini_hochberg(frame["p_value"].to_numpy())
    frame["significant_within_window"] = frame["q_within_window"] < ALPHA
    frame["significant_all_75_tests"] = frame["q_all_75_tests"] < ALPHA
    return frame
