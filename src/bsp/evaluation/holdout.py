"""The one-time hold-out evaluation (README Phase 9) and its rehearsal.

``python -m bsp.evaluation.holdout --mode rehearsal`` runs exactly the same code on the last two UNLOCKED budgets (FY2022-23,
FY2023-24) and writes ``reports/holdout_rehearsal.*``: it proves the machinery works before the hold-out is spent and is NOT
the hold-out result. ``--mode holdout`` evaluates FY2024-25 and FY2025-26 once and writes ``reports/holdout.*``.

The plan (models, primary and secondary decision rules, statistics) is frozen in config/holdout_plan.json with the code and data
(config/holdout_freeze.json). Procedure: the Phase 5 walk-forward is run unchanged with the evaluation budgets as extra test folds;
the earlier folds must reproduce the saved Phase 5 predictions (drift check); every model is reported, none is promoted.

Hold-out mode refuses to run unless: the config flag ``holdout_unlocked`` is true and ``holdout_spent`` false; ``reports/holdout.md``
does not exist; the freeze manifest still matches; the git tree is clean; HEAD carries the run tag; the freeze tag is an ancestor
of HEAD; and nothing but config/evaluation.json changed since the freeze tag. It prints no metric: results are written in one go
after everything is computed, so a crash before the write leaves nothing observed and the run may be repeated after fixing the crash.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from bsp.common.config import get_project_root
from bsp.evaluation import freeze
from bsp.evaluation.backtest import run_backtest, top_k_selection
from bsp.evaluation.config import EvalConfig, load_config
from bsp.evaluation.data import budget_calendar, load_sector_panel, trading_days
from bsp.evaluation.run_baselines import BENCHMARK, _cross_section_metrics, _fmt, _table
from bsp.evaluation.walk_forward import Model, stack_predictions, walk_forward
from bsp.explain.build import build_outputs
from bsp.features.baskets import build_market_data_bundle
from bsp.models.baselines import (
    EqualWeight,
    RidgeBaseline,
    biggest_allocation_increase,
    last_years_winners,
    make_ridge_tuner,
)
from bsp.models.ensemble import tier1_features
from bsp.models.run_models import _stock_metrics, run_sector_models, run_stock_models

MODES = ("rehearsal", "holdout")
NAN = float("nan")


def load_plan(root: Path) -> dict[str, Any]:
    return json.loads((root / "config" / "holdout_plan.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def check_preconditions(cfg: EvalConfig, plan: dict[str, Any], root: Path, git: Any = _git) -> list[str]:
    """Every reason the one-time hold-out run must not start now (empty list = allowed)."""
    problems: list[str] = []
    if not cfg.holdout_unlocked:
        problems.append('config/evaluation.json: "holdout_unlocked" is false')
    if cfg.holdout_spent:
        problems.append("the hold-out has already been spent (holdout_spent is true)")
    if (root / "reports" / "holdout.md").exists() or (root / "reports" / "holdout_result.json").exists():
        problems.append("hold-out results already exist (reports/holdout.md or holdout_result.json)")
    problems += [f"freeze manifest: {p}" for p in freeze.verify(root)]
    try:
        if git(root, "status", "--porcelain"):
            problems.append("the git working tree is not clean")
        head = git(root, "rev-parse", "HEAD")
        run_tag = git(root, "rev-parse", f"{plan['run_tag']}^{{commit}}")
        if head != run_tag:
            problems.append(f"HEAD is not the commit tagged {plan['run_tag']}")
        freeze_tag = git(root, "rev-parse", f"{plan['freeze_tag']}^{{commit}}")
        try:
            git(root, "merge-base", "--is-ancestor", freeze_tag, head)
        except subprocess.CalledProcessError:
            problems.append(f"{plan['freeze_tag']} is not an ancestor of HEAD")
        changed = set(git(root, "diff", "--name-only", freeze_tag, head).splitlines())
        extra = sorted(changed - {"config/evaluation.json"})
        if extra:
            problems.append(f"files changed since {plan['freeze_tag']}: {', '.join(extra)}")
    except subprocess.CalledProcessError as exc:
        problems.append(f"git check failed ({exc.cmd[-2:]}): is the tag missing?")
    return problems


@dataclass
class Outcome:
    metrics: pd.DataFrame
    predictions: pd.DataFrame
    verdicts: dict[str, dict[str, object]]
    drift: dict[str, float]
    control: pd.DataFrame


def _baseline_predictions(cfg: EvalConfig, panel: Any) -> dict[str, pd.DataFrame]:
    specs: list[tuple[str, Callable[..., Model], Any]] = [("equal_weight", lambda: EqualWeight(), None), ("last_years_winners", lambda: last_years_winners(), None),
             ("biggest_allocation_increase", lambda: biggest_allocation_increase(), None),
             ("ridge", lambda alpha=10.0: RidgeBaseline(alpha=alpha, interval_level=cfg.interval_level), make_ridge_tuner(cfg.ridge_alpha_grid))]
    return {name: stack_predictions(walk_forward(panel, factory, cfg, tune)) for name, factory, tune in specs}


def _drift(sector_predictions: dict[str, pd.DataFrame], root: Path, eval_budgets: set[str]) -> dict[str, float]:
    """Largest absolute difference between the recomputed and the saved Phase 5 predictions on the earlier folds (must be ~0)."""
    saved = pd.concat([pd.read_csv(root / "reports" / "baselines_predictions_sector.csv"), pd.read_csv(root / "reports" / "models_predictions_sector.csv")])
    out: dict[str, float] = {}
    for model, frame in sector_predictions.items():
        old = saved[saved["model"] == model].drop_duplicates(["budget_id", "entity"])
        new = frame[~frame["budget_id"].isin(eval_budgets)]
        merged = new.merge(old, on=["budget_id", "entity"], suffixes=("", "_saved"))
        if len(merged) != len(new):
            out[model] = float("inf")
            continue
        out[model] = float(np.nanmax(np.abs(merged["score"] - merged["score_saved"]))) if len(merged) else NAN
    return out


def compute(cfg: EvalConfig, plan: dict[str, Any], mode: str, root: Path) -> Outcome:
    eval_budgets = list(plan["eval_budgets"][mode])
    include_locked = mode == "holdout"
    bundle = build_market_data_bundle(root)
    panel = load_sector_panel(cfg, include_locked=include_locked)
    calendar = budget_calendar(root, trading_days(root))
    windows = calendar[["budget_id", "start", "label_end"]]
    market_level = pd.DataFrame({BENCHMARK: (1.0 + bundle.market_returns.fillna(0.0)).cumprod()})
    all_budgets = sorted(panel.frame["budget_id"].unique())
    bench_all = run_backtest({b: [BENCHMARK] for b in all_budgets}, windows[windows["budget_id"].isin(all_budgets)], market_level, cfg.round_trip_cost)

    sector_runs, sector_folds, stack_weights = run_sector_models(cfg, panel, windows, bundle, bench_all)
    preds = _baseline_predictions(cfg, panel)
    preds.update({name: run.predictions for name, run in sector_runs.items()})
    drift = _drift(preds, root, set(eval_budgets) if include_locked else set())  # rehearsal: every fold is already saved, check all of them
    tier1 = tier1_features(preds["tier1_blend"])
    stock_runs, stock_panel = run_stock_models(cfg, tier1, windows, bundle, bench_all, include_locked=include_locked)

    bench = run_backtest({b: [BENCHMARK] for b in eval_budgets}, windows[windows["budget_id"].isin(eval_budgets)], market_level, cfg.round_trip_cost)
    bench_net = bench.periods.set_index("budget_id")["net_return"]
    sector_levels = (1.0 + bundle.sector_returns.fillna(0.0)).cumprod()
    stock_levels = (1.0 + bundle.stock_returns.fillna(0.0)).cumprod()
    rows: list[dict[str, object]] = []
    for level, models, frames, levels, k in (("sector", plan["sector_models"], preds, sector_levels, cfg.top_k_sectors),
                                            ("stock", plan["stock_models"], {n: r.predictions for n, r in stock_runs.items()}, stock_levels, cfg.top_k_stocks)):
        for model in models:
            frame = frames[model]
            headline = frame[~frame["is_control"].astype(bool)]
            headline_eval = headline[headline["budget_id"].isin(eval_budgets)]
            selections = top_k_selection(headline_eval, k, model == "equal_weight")
            backtest = run_backtest(selections, windows[windows["budget_id"].isin(selections)], levels, cfg.round_trip_cost)
            port = backtest.periods.set_index("budget_id")["net_return"]
            for budget, group in headline_eval.groupby("budget_id"):
                metric = _cross_section_metrics(group) if level == "sector" else _stock_metrics(group, k)
                rows.append({"level": level, "model": model, "budget_id": budget, **metric, "port_net": float(port.get(budget, NAN)),
                             "bench_net": float(bench_net.get(budget, NAN)), "port_excess": float(port.get(budget, NAN) - bench_net.get(budget, NAN))})
    metrics = pd.DataFrame(rows)

    stock_pred = stock_runs["tier2_ranker"].predictions
    explained = build_outputs(root, cfg.seed, panel.frame, stock_panel.frame, sector_folds, {n: sector_runs[n].predictions for n in sector_runs},
                              stack_weights, stock_runs["tier2_ranker"].folds or [], stock_pred,
                              panel.frame.drop_duplicates("budget_id")[["budget_id", "presented_on", "day0", "label_end"]], set(eval_budgets))
    detail = explained.detail[explained.detail["budget_id"].isin(eval_budgets)].copy()
    cover = detail[~detail["is_control"].astype(bool)].dropna(subset=["actual"]).copy()
    cover["covered"] = (cover["actual"] >= cover["p10"]) & (cover["actual"] <= cover["p90"])
    coverage = cover.groupby(["model", "level"]).agg(n=("covered", "size"), coverage=("covered", "mean"), mean_width=("p90", "size")).reset_index()
    coverage["mean_width"] = cover.assign(w=cover["p90"] - cover["p10"]).groupby(["model", "level"])["w"].mean().to_numpy()

    control_rows = []
    for model in plan["sector_models"]:
        for budget, group in preds[model][preds[model]["budget_id"].isin(eval_budgets)].groupby("budget_id"):
            if not group["is_control"].any() or group["score"].nunique() < 2:
                continue
            ranks = rankdata(-group["score"].to_numpy(), method="average")
            actual_ranks = rankdata(-group["actual"].fillna(group["actual"].min()).to_numpy(), method="average")
            i = int(np.flatnonzero(group["is_control"].to_numpy())[0])
            control_rows.append({"model": model, "budget_id": budget, "predicted_rank": float(ranks[i]), "actual_rank": float(actual_ranks[i]),
                                 "n_sectors": len(group), "in_predicted_top3": bool(ranks[i] <= 3)})
    control = pd.DataFrame(control_rows)
    return Outcome(metrics, detail, verdicts(plan, metrics, coverage, control, eval_budgets), drift, control)


def verdicts(plan: dict[str, Any], metrics: pd.DataFrame, coverage: pd.DataFrame, control: pd.DataFrame, eval_budgets: list[str]) -> dict[str, dict[str, object]]:
    """Apply the pre-registered rules mechanically to the numbers."""
    out: dict[str, dict[str, object]] = {}

    def per_budget(level: str, model: str, column: str) -> list[float]:
        g = metrics[(metrics["level"] == level) & (metrics["model"] == model)].set_index("budget_id")[column]
        return [float(g.get(b, NAN)) for b in eval_budgets]

    primary = plan["primary"]
    ic = per_budget(primary["level"], primary["model"], "ic")
    out[primary["id"]] = {"rule": primary["rule"], "values": ic, "display": "IC " + ", ".join(_fm(v) for v in ic),
                          "met": bool(all(v >= primary["bar"] for v in ic))}
    blend, eqw = per_budget("sector", "tier1_blend", "port_net"), per_budget("sector", "equal_weight", "port_net")
    diff1 = [a - b for a, b in zip(blend, eqw, strict=True)]
    out["S1"] = {"rule": plan["secondary"][0]["rule"], "values": diff1, "display": "net return minus equal weight: " + ", ".join(_fm(v, pct=True) for v in diff1),
                 "met": bool(all(v > 0 for v in diff1))}
    cov = coverage[(coverage["model"] == "tier1_blend") & (coverage["level"] == "sector")]
    c = float(cov["coverage"].iloc[0]) if len(cov) else NAN
    out["S2"] = {"rule": plan["secondary"][1]["rule"], "values": [c], "display": "coverage " + _fm(c, pct=True), "met": bool(0.75 <= c <= 0.85)}
    ic2, t2, e2 = per_budget("stock", "tier2_ranker", "ic"), per_budget("stock", "tier2_ranker", "port_net"), per_budget("stock", "equal_weight", "port_net")
    diff3 = [a - b for a, b in zip(t2, e2, strict=True)]
    out["S3"] = {"rule": plan["secondary"][2]["rule"], "values": ic2 + diff3,
                 "display": "IC " + ", ".join(_fm(v) for v in ic2) + "; net return minus equal weight: " + ", ".join(_fm(v, pct=True) for v in diff3),
                 "met": bool(all(v > 0 for v in ic2) and all(v > 0 for v in diff3))}
    top3 = control[control["model"] == "tier1_blend"].set_index("budget_id")["in_predicted_top3"]
    in_top = [bool(top3.get(b, False)) for b in eval_budgets]
    out["S4"] = {"rule": plan["secondary"][3]["rule"], "values": in_top, "display": "IT in predicted top 3: " + ", ".join("yes" if v else "no" for v in in_top),
                 "met": not all(in_top)}
    return out


def _fm(v: object, pct: bool = False, d: int = 3) -> str:
    return _fmt(float(v), d, pct)  # type: ignore[arg-type]


def write_outputs(outcome: Outcome, plan: dict[str, Any], mode: str, root: Path, run_info: dict[str, object]) -> None:
    prefix = "holdout" if mode == "holdout" else "holdout_rehearsal"
    reports = root / "reports"
    eval_budgets = plan["eval_budgets"][mode]
    outcome.metrics.round(8).to_csv(reports / f"{prefix}_metrics.csv", index=False)
    keep = ["model", "level", "entity", "budget_id", "expected_excess", "p10", "p90", "p_beat", "rank", "top_reasons", "actual", "interval_method"]
    outcome.predictions[keep].round(8).to_csv(reports / f"{prefix}_predictions.csv", index=False)
    outcome.control.to_csv(reports / f"{prefix}_control_sector.csv", index=False)
    title = "Hold-out evaluation (FY2024-25 and FY2025-26): the one-time run" if mode == "holdout" else "Hold-out REHEARSAL on FY2022-23 and FY2023-24 (NOT the hold-out)"
    out = [f"# {title}", ""]
    if mode == "rehearsal":
        out += ["**This is a rehearsal of the hold-out machinery on two already-unlocked budgets. It is not the hold-out result and says nothing about "
                "FY2024-25 or FY2025-26.** It exists to show, before the hold-out is spent, that the runner works end to end and that its earlier folds "
                "reproduce the saved Phase 5 predictions.", ""]
    else:
        out += ["Produced by exactly one run of `python -m bsp.evaluation.holdout --mode holdout` at the tagged commit below. Nothing was re-tuned "
                "after seeing it. This is descriptive: two budgets cannot support a significance test.", ""]
    out += [f"- Evaluation budgets: {', '.join(eval_budgets)}. Plan: `config/holdout_plan.json` (frozen before the run). Procedure: {plan['procedure']}",
            f"- {plan['statistics']}",
            f"- Not included: {'; '.join(plan['not_included'])}.",
            f"- Run: commit `{run_info.get('commit', '?')}`, tag `{run_info.get('tag', 'n/a')}`, freeze tag `{plan['freeze_tag']}`.",
            "- Drift check (largest absolute difference between the recomputed and the saved Phase 5 scores on every fold that was already saved): "
            + ", ".join(f"{m} {v:.1e}" for m, v in outcome.drift.items()) + ".", ""]
    out += ["## Pre-registered decision rules, applied mechanically", ""]
    rows = [[rid, str(v["rule"]), str(v["display"]), "**MET**" if v["met"] else "not met"] for rid, v in outcome.verdicts.items()]
    out += [_table(["Rule", "Statement", "Values (per budget)", "Result"], rows), "",
            "P1 is the primary rule; S1-S4 are secondary; values are listed per budget in the order of the evaluation budgets above. "
            "No model is selected or promoted because of these results.", ""]
    for level, title2 in (("sector", "Sector models (14 budget-sensitive sectors)"), ("stock", "Stock models (top-15 portfolios)")):
        g = outcome.metrics[outcome.metrics["level"] == level]
        out += [f"## {title2}", ""]
        header = ["Model", "Budget", "IC", "Top-3 hit" if level == "sector" else "Within-sector IC", "Top-k net return", "Nifty 500", "Excess"]
        rows = [[str(r["model"]), str(r["budget_id"]), _fm(r["ic"]), _fm(r["top3_hit"], pct=True) if level == "sector" else _fm(r["within_sector_ic"]),
                 _fm(r["port_net"], pct=True), _fm(r["bench_net"], pct=True), _fm(r["port_excess"], pct=True)] for r in g.to_dict("records")]
        out += [_table(header, rows), ""]
        mean = g.groupby("model")[["ic", "port_net", "port_excess"]].mean().reset_index()
        out += ["Mean over the two budgets:", "", _table(["Model", "Mean IC", "Mean net return", "Mean excess vs Nifty 500"],
                [[str(r["model"]), _fm(r["ic"]), _fm(r["port_net"], pct=True), _fm(r["port_excess"], pct=True)] for r in mean.to_dict("records")]), ""]
    cov = outcome.predictions[~outcome.predictions["is_control"].astype(bool)].dropna(subset=["actual"]).copy()
    cov["covered"] = (cov["actual"] >= cov["p10"]) & (cov["actual"] <= cov["p90"])
    table = cov.groupby(["model", "level"]).agg(n=("covered", "size"), coverage=("covered", "mean")).reset_index()
    out += ["## Interval coverage (80% target, 75-85% accepted)", "",
            _table(["Model", "Level", "Forecasts", "Coverage"], [[str(r["model"]), str(r["level"]), str(r["n"]), _fm(r["coverage"], pct=True)] for r in table.to_dict("records")]), "",
            "Intervals are walk-forward conformal (Phase 7), calibrated on earlier resolved out-of-sample errors only.", ""]
    c = outcome.control
    out += ["## IT Services (control sector)", "", _table(["Model", "Budget", "Predicted rank (of 15)", "Realised rank"],
            [[str(r["model"]), str(r["budget_id"]), _fm(r["predicted_rank"], d=1), _fm(r["actual_rank"], d=1)] for r in c.to_dict("records")]), "",
            "Predictions with their three reasons and intervals: `reports/" + f"{prefix}_predictions.csv`.", ""]
    (reports / f"{prefix}.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    (reports / f"{prefix}_result.json").write_text(json.dumps({**run_info, "mode": mode, "verdicts": outcome.verdicts, "drift": outcome.drift},
                                                              indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, required=True)
    args = parser.parse_args()
    root = get_project_root()
    cfg = load_config()
    plan = load_plan(root)
    run_info: dict[str, object] = {"freeze_tag": plan["freeze_tag"]}
    if args.mode == "holdout":
        problems = check_preconditions(cfg, plan, root)
        if problems:
            raise SystemExit("REFUSED: the one-time hold-out run is not allowed yet:\n  - " + "\n  - ".join(problems))
        run_info.update({"commit": _git(root, "rev-parse", "HEAD"), "tag": plan["run_tag"]})
    else:
        run_info.update({"commit": _git(root, "rev-parse", "HEAD"), "tag": "n/a (rehearsal)"})
    outcome = compute(cfg, plan, args.mode, root)
    drift_bad = {m: v for m, v in outcome.drift.items() if not (v <= 1e-6)}
    if drift_bad and args.mode == "holdout":
        raise SystemExit(f"STOPPED before writing any hold-out result: the earlier folds no longer reproduce Phase 5 ({drift_bad}); nothing was observed.")
    write_outputs(outcome, plan, args.mode, root, run_info)
    print(f"wrote reports/{'holdout' if args.mode == 'holdout' else 'holdout_rehearsal'}.md" + (" and the other hold-out files" if args.mode == "holdout" else ""))
    if args.mode == "rehearsal":
        for rid, v in outcome.verdicts.items():
            print(rid, "MET" if v["met"] else "not met")


if __name__ == "__main__":
    main()
