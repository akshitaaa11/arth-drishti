"""Speech features for the sector-year feature store (README Phase 6, F6 "talk vs money").

Point in time: a budget speech is public on budget day and the 12m target window starts the trading day after day 0
(``evaluation/data.py``), so a feature built from budget t's own speech and nothing else is legitimate on budget day. The feature
rows carry the same ``as_of_date`` (<= the budget date) as every other feature, and a budget's features use only that budget's
own sentences (``tests/test_speech.py`` shows another speech cannot change them).

Features per sector and budget (all missing, never 0, when the budget has no speech in data/csv/speech_sentences.csv):
  speech_emphasis           share of the speech's sentences that mention the sector (keyword tagging, speech_tagging.py)
  speech_new_scheme_n       tagged sentences with an announcement cue (new scheme, launch, set up, establish, propose ...)
  speech_emphasis_rank      1 = most emphasised sector of this budget (average rank for ties), among sectors with a score
  talk_vs_money_divergence  (emphasis rank - allocation-surprise rank) / n, the two ranks taken over the n sectors that have
                            both an emphasis and an ``alloc_vs_prev_re_pct``; rank 1 = highest. Negative = more talk than money
                            (the speech stresses the sector more than the allocation surprise does); positive = more money
                            than talk. Dividing by n keeps it comparable when the surprise is missing for some sectors.
There is no sentiment feature (no sentiment model is available here).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

SPEECH_FEATURES = ["speech_emphasis", "speech_new_scheme_n", "speech_emphasis_rank", "talk_vs_money_divergence"]


def load_speech_scores(root: Path) -> pd.DataFrame:
    path = root / "data" / "csv" / "speech_sector_scores.csv"
    if not path.exists():
        return pd.DataFrame(columns=["budget_id", "sector_id", "emphasis", "new_scheme_n"])
    return pd.read_csv(path)


def add_speech_features(records: list[dict[str, Any]], scores: pd.DataFrame) -> None:
    """Fill the four speech features into the wide feature records (in place), budget by budget."""
    lookup = {(str(r["budget_id"]), str(r["sector_id"])): (float(r["emphasis"]), float(r["new_scheme_n"]))
              for r in scores.to_dict("records")}
    by_budget: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = (str(record["budget_id"]), str(record["sector_id"]))
        emphasis, new_n = lookup.get(key, (None, None))
        record["speech_emphasis"], record["speech_new_scheme_n"] = emphasis, new_n
        record["speech_emphasis_rank"] = None
        record["talk_vs_money_divergence"] = None
        by_budget.setdefault(str(record["budget_id"]), []).append(record)
    for rows in by_budget.values():
        scored = [r for r in rows if r["speech_emphasis"] is not None]
        if not scored:
            continue
        ranks = pd.Series([r["speech_emphasis"] for r in scored]).rank(ascending=False, method="average")
        for record, rank in zip(scored, ranks, strict=True):
            record["speech_emphasis_rank"] = float(rank)
        both = [r for r in scored if r.get("alloc_vs_prev_re_pct") is not None and pd.notna(r["alloc_vs_prev_re_pct"])]
        if len(both) < 2:
            continue
        e_rank = pd.Series([r["speech_emphasis"] for r in both]).rank(ascending=False, method="average")
        s_rank = pd.Series([float(r["alloc_vs_prev_re_pct"]) for r in both]).rank(ascending=False, method="average")
        for record, e, s in zip(both, e_rank, s_rank, strict=True):
            record["talk_vs_money_divergence"] = float((e - s) / len(both))
