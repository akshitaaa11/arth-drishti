"""Read-only data access for the API: every response is built from the committed CSVs, so the API needs no database.

Row references: a displayed number carries a ``source_ref`` of the form ``<dataset>:<row>`` (row = 0-based position in the CSV);
``/sources/{ref}`` returns that row and its provenance columns. Nothing here changes data or touches the locked hold-out: the
budgets listed as forecastable are those that have walk-forward predictions in ``reports/predictions_detail.csv`` (FY2012-13 to FY2023-24).
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import cached_property
from pathlib import Path
from typing import Any

import pandas as pd

from bsp.common.config import get_project_root

DATASETS = {
    "budget_ministries": "data/csv/budget_ministries.csv", "budget_schemes": "data/csv/budget_schemes.csv",
    "budget_fiscal": "data/csv/budget_fiscal.csv", "budget_demands": "data/csv/budget_demands.csv",
    "sector_budget_panel": "data/csv/sector_budget_panel.csv", "features_sector_year_wide": "data/csv/features_sector_year_wide.csv",
    "features_stock_year_wide": "data/csv/features_stock_year_wide.csv", "event_study": "data/csv/event_study.csv",
    "fpi_sector_fortnightly": "data/csv/fpi_sector_fortnightly.csv", "predictions_detail": "reports/predictions_detail.csv",
    "shap_values_sector": "reports/shap_values_sector.csv", "backtest_lab_summary": "reports/backtest_lab_summary.csv",
    "ic_bootstrap": "reports/ic_bootstrap.csv", "ablation_summary": "reports/ablation_summary.csv",
    "did_summary": "reports/did_summary.csv", "models_per_year": "reports/models_per_year.csv", "event_effects_bh": "reports/event_effects_bh.csv",
}
DATASET_NOTES = {
    "budget_ministries": "PRS Legislative Research Union Budget Analysis PDFs, parsed by scripts/parse_prs.py (make parse-pdfs)",
    "budget_schemes": "PRS Legislative Research Union Budget Analysis PDFs, parsed by scripts/parse_prs.py (make parse-pdfs)",
    "budget_fiscal": "PRS Legislative Research Union Budget Analysis PDFs, parsed by scripts/parse_prs.py (make parse-pdfs)",
    "budget_demands": "Expenditure Budget Statement 3 (indiabudget.gov.in), parsed by scripts/build_statement3.py",
    "sector_budget_panel": "Built from the Expenditure Budget and PRS tables by scripts/build_budget_csvs.py",
    "features_sector_year_wide": "Point-in-time sector features built by `make features` (bsp.features.sector_features) from the budget, price, FPI and macro CSVs",
    "features_stock_year_wide": "Point-in-time stock features built by `make features` (bsp.features.stock_features) from prices_daily.csv (Yahoo Finance)",
    "event_study": "Market-model event study built by `make features` (bsp.events.study) from prices and the Nifty 500",
    "fpi_sector_fortnightly": "NSDL fortnightly sector-wise FPI reports, collected by bsp.ingest.fpi",
    "predictions_detail": "Out-of-sample walk-forward predictions from `make train` (bsp.models.run_models) with Phase 7 intervals and reasons",
    "shap_values_sector": "SHAP attributions of the walk-forward sector models from `make train` (bsp.explain)",
    "backtest_lab_summary": "Backtests rebuilt from saved predictions by `make evidence` (bsp.evidence.backtest_lab)",
    "ic_bootstrap": "Year-level bootstrap of out-of-sample IC by `make evidence` (bsp.evidence.run_evidence)",
    "ablation_summary": "Feature-family ablations by `make evidence` (bsp.evidence.ablation)",
    "did_summary": "Difference-in-differences by `make evidence` (bsp.evidence.did)",
    "event_effects_bh": "Sector event effects with Benjamini-Hochberg correction by `make evidence`",
    "models_per_year": "Per-year metrics of the Phase 4 baselines and Phase 5 models (make backtest, make train)",
}
PROVENANCE = ["source", "source_doc", "source_page", "source_url", "fetched_at", "extraction_method", "table_no", "table_title"]
PRIMARY_SECTOR_MODEL, PRIMARY_STOCK_MODEL = "tier1_blend", "tier2_ranker"
WINDOW_ORDER = ["[-5,-1]", "0", "[0,+5]", "[0,+30]", "[0,+90]"]


def clean(value: Any) -> Any:
    """JSON-safe copy: NaN / inf become None, numpy scalars become Python numbers."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except Exception:
            return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [clean(r) for r in frame.to_dict("records")]


class Store:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_project_root()

    # ------------------------------------------------------------------ raw tables
    def _csv(self, dataset: str) -> pd.DataFrame:
        path = self.root / DATASETS[dataset]
        frame = pd.read_csv(path)
        frame["_row"] = range(len(frame))
        return frame

    def table(self, dataset: str) -> pd.DataFrame:
        cache = self.__dict__.setdefault("_tables", {})
        if dataset not in cache:
            cache[dataset] = self._csv(dataset)
        return cache[dataset]

    @cached_property
    def sector_map(self) -> list[dict[str, Any]]:
        return json.loads((self.root / "config" / "sector_map.json").read_text(encoding="utf-8"))["sectors"]  # type: ignore[no-any-return]

    @cached_property
    def events(self) -> pd.DataFrame:
        return pd.read_csv(self.root / "config" / "budget_events.csv")

    @cached_property
    def evaluation(self) -> dict[str, Any]:
        return json.loads((self.root / "config" / "evaluation.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    # ------------------------------------------------------------------ budgets
    def budget_status(self, budget_id: str, fiscal_year: str, budget_type: str) -> str:
        ev = self.evaluation
        if fiscal_year in ev["live_fiscal_years"]:
            return "live_sealed"
        if fiscal_year in ev["holdout_fiscal_years"]:
            return "holdout_evaluated" if ev.get("holdout_spent") else "holdout_locked"
        return "interim_not_modelled" if budget_type == "interim" else "walk_forward_test"

    def budgets(self) -> list[dict[str, Any]]:
        detail = self.table("predictions_detail")
        forecasted = set(detail["budget_id"])
        panel = self.table("sector_budget_panel")
        years_with_lines = set(self.table("budget_ministries")["budget_year"].astype(str))
        out = []
        for e in self.events.to_dict("records"):
            status = self.budget_status(e["budget_id"], str(e["fiscal_year"]), e["budget_type"])
            out.append({**{k: e[k] for k in ("budget_id", "fiscal_year", "presented_on", "budget_type", "finance_minister")},
                        "is_election_year": bool(e["is_election_year"]), "status": status, "has_forecast": e["budget_id"] in forecasted,
                        "has_budget_lines": str(e["fiscal_year"]) in years_with_lines and e["budget_type"] == "full",
                        "has_sector_panel": bool((panel["budget_year"] == e["fiscal_year"]).any()) and e["budget_type"] == "full",
                        "has_speech": False})
        speech = self.root / "data" / "csv" / "speech_sector_scores.csv"
        if speech.exists():
            have = set(pd.read_csv(speech)["budget_id"])
            for b in out:
                b["has_speech"] = b["budget_id"] in have
        return out

    def budget(self, budget_id: str) -> dict[str, Any] | None:
        return next((b for b in self.budgets() if b["budget_id"] == budget_id), None)

    def latest_forecast_budget(self) -> str:
        detail = self.table("predictions_detail")
        return str(self.events[self.events["budget_id"].isin(set(detail["budget_id"]))].sort_values("presented_on")["budget_id"].iloc[-1])

    # ------------------------------------------------------------------ budget lines
    LINE_FILES = {"ministry": "budget_ministries", "scheme": "budget_schemes", "fiscal": "budget_fiscal"}

    def lines(self, budget_id: str, kind: str) -> list[dict[str, Any]]:
        """Line items of one budget (the publication year's table): Actual, RE and BE with a source reference each."""
        budget = self.budget(budget_id)
        if budget is None:
            return []
        year = str(budget["fiscal_year"])
        if kind == "demand":
            d = self.table("budget_demands")
            d = d[d["budget_year"].astype(str) == year]
            items = []
            for (ministry, stage), g in d.groupby(["ministry", "stage"]):
                items.append({"ministry": ministry, "stage": stage, "fiscal_year": str(g["fiscal_year"].iloc[0]), "revenue_cr": float(g["revenue_cr"].sum()),
                              "capital_cr": float(g["capital_cr"].sum()), "total_cr": float(g["total_cr"].sum()), "source_ref": f"budget_demands:{int(g['_row'].iloc[0])}"})
            return clean(items)  # type: ignore[no-any-return]
        dataset = self.LINE_FILES[kind]
        frame = self.table(dataset)
        frame = frame[frame["budget_year"].astype(str) == year]
        out: dict[str, dict[str, Any]] = {}
        for r in frame.to_dict("records"):
            item = out.setdefault(str(r["canonical_name"]), {"line_item": r["canonical_name"], "kind": kind, "unit": r["unit"]})
            item[str(r["stage"]).lower()] = {"fiscal_year": str(r["fiscal_year"]), "amount_cr": r["amount_cr"], "source_ref": f"{dataset}:{int(r['_row'])}",
                                             "source_doc": r["source_doc"], "source_page": r["source_page"]}
        return clean(list(out.values()))  # type: ignore[no-any-return]

    # ------------------------------------------------------------------ forecasts
    def sector_info(self, sector_id: str) -> dict[str, Any] | None:
        return next((s for s in self.sector_map if s["sector_id"] == sector_id), None)

    def forecasts(self, budget_id: str, level: str, model: str) -> pd.DataFrame:
        d = self.table("predictions_detail")
        d = d[(d["budget_id"] == budget_id) & (d["level"] == level) & (d["model"] == model)] if "model" in d else d[0:0]
        return d.sort_values("rank")

    def forecast_row(self, row: pd.Series) -> dict[str, Any]:
        reasons = json.loads(row["top_reasons"]) if isinstance(row.get("top_reasons"), str) else []
        return clean({"entity": row["entity"], "sector_id": row["sector_id"], "model": row["model"], "budget_id": row["budget_id"],
                      "expected_excess": row["expected_excess"], "p10": row["p10"], "p90": row["p90"], "p_beat": row["p_beat"], "rank": int(row["rank"]),
                      "interval_method": row.get("interval_method"), "reasons": reasons, "realised_excess": row.get("actual"),
                      "is_control": bool(row["is_control"]), "source_ref": f"predictions_detail:{int(row['_row'])}"})

    def shap_for(self, budget_id: str, entity: str, model: str = PRIMARY_SECTOR_MODEL) -> list[dict[str, Any]]:
        s = self.table("shap_values_sector")
        s = s[(s["budget_id"] == budget_id) & (s["entity"] == entity) & (s["model"] == model) & (s["target"] == "expected_return")]
        return records(s[["feature", "feature_value", "base", "shap", "_row"]].rename(columns={"_row": "row"}).sort_values("shap", key=lambda c: -c.abs()))

    # ------------------------------------------------------------------ provenance
    def source_row(self, ref: str) -> dict[str, Any] | None:
        dataset, _, row = ref.partition(":")
        if dataset not in DATASETS or not row.isdigit():
            return None
        frame = self.table(dataset)
        i = int(row)
        if i >= len(frame):
            return None
        record = frame.iloc[i].drop("_row").to_dict()
        path = self.root / DATASETS[dataset]
        return clean({"ref": ref, "dataset": dataset, "file": DATASETS[dataset], "row": i, "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "provenance": {"produced_by": DATASET_NOTES.get(dataset, ""), **{k: record[k] for k in PROVENANCE if k in record}}, "row_values": record})
