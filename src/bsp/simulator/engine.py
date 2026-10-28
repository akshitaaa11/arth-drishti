"""What-if engine (README Phase 10, F3): change a sector's allocation, rebuild the affected features, re-score Tier 1 with SHAP.

A scenario sets, per sector, a percentage change to that budget's allocation (``be_current_cr``). The two features that depend on it are
rebuilt with the same formulas as the feature store:
    alloc_vs_prev_re_pct  = (BE_new / RE_previous - 1) x 100        (surprise against last year's revised estimate)
    growth_vs_prev_be_pct = (BE_new / BE_previous - 1) x 100
Everything else (momentum, credibility, macro, ...) is left as it was on budget day. A sector with no previous BE or RE keeps its feature
missing: it cannot be changed.

Scoring uses the Tier-1 LightGBM model (ranker for the order, companion regressor for the expected excess return, SHAP for the reasons),
refit once on every UNLOCKED, resolved row with the default parameters (no tuning; the hold-out and live years are never loaded). For a historical budget
this model has seen that budget's own outcome, so the numbers are not out-of-sample forecasts; the actual-budget and scenario scores use the
same model, so their difference isolates the allocation change. It is an illustration of how the model reads the allocation, not a forecast.
Presets replay real history: ``actual``, ``flat_vs_re`` (every allocation equal to last year's revised estimate) and ``replay:<budget_id>``
(every sector's allocation grows by the rate it actually grew in that other budget).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bsp.common.config import get_project_root
from bsp.evaluation.config import load_config
from bsp.evaluation.data import load_sector_panel
from bsp.explain import contributions as con
from bsp.explain.reasons import reasons_for
from bsp.models.ranker import LGBMRankerModel

DISCLAIMER = ("Illustration of how the Tier-1 model reads the allocation, not a forecast: the model is refit on all unlocked history with default "
              "parameters and has seen the historical budget's own outcome.")


class SimulationError(ValueError):
    pass


class Simulator:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_project_root()
        cfg = load_config(self.root)
        panel = load_sector_panel(cfg)
        self.frame = panel.frame
        self.features = panel.features
        rows = self.frame[self.frame["target_complete"] & self.frame["excess_return"].notna()]
        self.model = LGBMRankerModel(seed=cfg.seed).fit(rows, self.features)
        names = pd.read_csv(self.root / "config" / "budget_events.csv")
        self.budgets = [b for b in names["budget_id"] if b in set(self.frame["budget_id"])]
        self.sector_names = {r["sector_id"]: r["sector_name"] for r in self.frame.drop_duplicates("entity")[["sector_id", "sector_name"]].to_dict("records")} \
            if "sector_name" in self.frame else {}

    def presets(self) -> list[dict[str, str]]:
        out = [{"id": "actual", "label": "Actual budget (no change)"},
               {"id": "flat_vs_re", "label": "Every allocation equal to last year's revised estimate (zero surprise)"}]
        out += [{"id": f"replay:{b}", "label": f"Replay: each sector grows by the rate it actually grew in {b}"} for b in self.budgets]
        return out

    def _rows(self, budget_id: str) -> pd.DataFrame:
        rows = self.frame[self.frame["budget_id"] == budget_id].reset_index(drop=True)
        if rows.empty:
            raise SimulationError(f"{budget_id} cannot be simulated: only unlocked full budgets with features are available ({self.budgets[0]} to {self.budgets[-1]})")
        return rows

    def _changes_from_preset(self, rows: pd.DataFrame, preset: str) -> dict[str, float]:
        changes: dict[str, float] = {}
        if preset == "actual":
            return changes
        if preset == "flat_vs_re":
            for r in rows.to_dict("records"):
                if pd.notna(r["re_previous_cr"]) and pd.notna(r["be_current_cr"]) and r["be_current_cr"]:
                    changes[r["entity"]] = float((r["re_previous_cr"] / r["be_current_cr"] - 1) * 100)
            return changes
        if preset.startswith("replay:"):
            other = self._rows(preset.split(":", 1)[1])
            growth = other.set_index("entity")["growth_vs_prev_be_pct"]
            for r in rows.to_dict("records"):
                g = growth.get(r["entity"])
                if g is not None and pd.notna(g) and pd.notna(r["be_previous_cr"]) and pd.notna(r["be_current_cr"]) and r["be_current_cr"]:
                    changes[r["entity"]] = float(r["be_previous_cr"] * (1 + g / 100) / r["be_current_cr"] * 100 - 100)
            return changes
        raise SimulationError(f"unknown preset {preset!r}")

    def _score(self, rows: pd.DataFrame) -> tuple[pd.DataFrame, con.Attribution]:
        out = self.model.predict(rows)
        scored = rows[["entity"]].copy()
        scored["score"], scored["expected"] = out["score"].to_numpy(), out["expected"].to_numpy()
        scored["rank"] = scored["score"].rank(ascending=False, method="first").astype(int)
        return scored, con.lgbm_expected_attribution(self.model, rows)

    def run(self, budget_id: str, changes: dict[str, float] | None = None, preset: str | None = None) -> dict[str, Any]:
        rows = self._rows(budget_id)
        sectors = set(rows["entity"])
        explicit = {k: float(v) for k, v in (changes or {}).items()}
        unknown = sorted(set(explicit) - sectors)
        if unknown:
            raise SimulationError(f"unknown sector(s): {', '.join(unknown)}")
        if any(abs(v) > 100 for v in explicit.values()) or any(not np.isfinite(v) for v in explicit.values()):
            raise SimulationError("allocation changes must be finite percentages between -100 and +100")
        applied = {**self._changes_from_preset(rows, preset or "actual"), **explicit}
        scenario = rows.copy()
        be_new = scenario["be_current_cr"].astype(float).copy()
        for sector, pct in applied.items():
            i = scenario.index[scenario["entity"] == sector][0]
            if pd.isna(rows.loc[i, "be_current_cr"]):
                continue
            be_new.loc[i] = float(rows.loc[i, "be_current_cr"]) * (1 + pct / 100)
            if pd.notna(rows.loc[i, "re_previous_cr"]) and rows.loc[i, "re_previous_cr"]:
                scenario.loc[i, "alloc_vs_prev_re_pct"] = (be_new.loc[i] / rows.loc[i, "re_previous_cr"] - 1) * 100
            if pd.notna(rows.loc[i, "be_previous_cr"]) and rows.loc[i, "be_previous_cr"]:
                scenario.loc[i, "growth_vs_prev_be_pct"] = (be_new.loc[i] / rows.loc[i, "be_previous_cr"] - 1) * 100
        base_scores, _ = self._score(rows)
        new_scores, attribution = self._score(scenario)
        result = []
        for i in range(len(rows)):
            r = rows.iloc[i]
            entity = r["entity"]
            contributions = {c: float(attribution.contrib[c].iloc[i]) for c in attribution.contrib.columns}
            values = {c: _num(scenario.iloc[i][c]) for c in attribution.contrib.columns}
            b, n = base_scores.iloc[i], new_scores.iloc[i]
            result.append({
                "sector_id": entity, "is_control": bool(r["is_control"]), "change_pct": applied.get(entity, 0.0),
                "be_actual_cr": _num(r["be_current_cr"]), "be_scenario_cr": _num(be_new.loc[i]),
                "surprise_actual_pct": _num(r["alloc_vs_prev_re_pct"]), "surprise_scenario_pct": _num(scenario.loc[i, "alloc_vs_prev_re_pct"]),
                "expected_actual": float(b["expected"]), "expected_scenario": float(n["expected"]),
                "expected_change": float(n["expected"] - b["expected"]), "rank_actual": int(b["rank"]), "rank_scenario": int(n["rank"]),
                "rank_change": int(b["rank"] - n["rank"]), "reasons": reasons_for(contributions, values, self.root)})
        return {"budget_id": budget_id, "preset": preset or "actual", "applied_changes_pct": applied, "sectors": result, "disclaimer": DISCLAIMER,
                "takeaway": _takeaway(result, applied)}


def _num(v: Any) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def _takeaway(result: list[dict[str, Any]], applied: dict[str, float]) -> str:
    if not applied:
        return "No allocation was changed, so the scenario equals the actual budget."
    touched = [r for r in result if r["sector_id"] in applied]
    lead = sorted(touched, key=lambda r: (abs(r["rank_change"]), abs(r["expected_change"])), reverse=True)[0]
    text = (f"Changing {lead['sector_id']}'s allocation by {lead['change_pct']:+.0f}% moves its surprise from "
            f"{_pp(lead['surprise_actual_pct'])} to {_pp(lead['surprise_scenario_pct'])}, its expected excess return by "
            f"{lead['expected_change'] * 100:+.1f} percentage points and its rank from {lead['rank_actual']} to {lead['rank_scenario']}.")
    if max(abs(r["expected_change"]) for r in result) < 0.02:
        text += " The model's expected returns barely react to allocation changes, in line with the Phase 8 finding that budget data adds little beyond price."
    return text


def _pp(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.1f}%"
