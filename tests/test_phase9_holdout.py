"""Phase 9: the hold-out stays locked, the freeze manifest, the run preconditions, the decision rules and the rehearsal outputs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from bsp.evaluation import freeze
from bsp.evaluation.config import HoldoutLockedError, load_config
from bsp.evaluation.data import load_sector_panel, load_stock_panel
from bsp.evaluation.holdout import check_preconditions, load_plan, verdicts

ROOT = Path(__file__).resolve().parents[1]
LOCKED = {"FY2024-25", "FY2025-26", "FY2026-27"}


def test_the_holdout_is_locked_in_the_committed_config_and_panels_exclude_it() -> None:
    cfg = load_config()
    assert not cfg.holdout_unlocked or cfg.holdout_spent is False  # unlocked only during the run commit
    if not cfg.holdout_unlocked:
        for panel in (load_sector_panel(cfg), load_stock_panel(cfg)):
            assert not set(panel.frame["budget_id"]) & LOCKED
        with pytest.raises(HoldoutLockedError):
            load_sector_panel(cfg, include_locked=True)
        with pytest.raises(HoldoutLockedError):
            load_stock_panel(cfg, include_locked=True)


def test_a_spent_holdout_cannot_be_unlocked(tmp_path: Path) -> None:
    raw = json.loads((ROOT / "config" / "evaluation.json").read_text())
    raw.update({"holdout_unlocked": True, "holdout_spent": True})
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "evaluation.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="cannot be unlocked after it has been spent"):
        load_config(tmp_path)


# ---------------------------------------------------------------- freeze manifest
def test_the_freeze_manifest_matches_the_tree_until_the_holdout_is_spent() -> None:
    cfg = load_config()
    if cfg.holdout_spent:
        pytest.skip("hold-out spent: the manifest is now a historical record, later phases change the code")
    assert freeze.verify(ROOT) == []


def test_the_manifest_records_settings_files_libraries_and_ignores_the_unlock_flag() -> None:
    manifest = json.loads((ROOT / freeze.MANIFEST).read_text())
    assert manifest["evaluation_settings"]["seed"] == 42 and manifest["evaluation_settings"]["holdout_fiscal_years"] == ["2024-25", "2025-26"]
    assert "src/bsp/evaluation/holdout.py" in manifest["source_files"] and "config/holdout_plan.json" in manifest["config_files"]
    assert "config/evaluation.json" not in manifest["config_files"]  # hashed by its modelling settings only
    assert {"lightgbm", "pymc", "scikit-learn"} <= set(manifest["libraries"])
    assert all(len(h) == 64 for h in manifest["source_files"].values())
    assert not any(f.split("/")[2] in ("api", "console", "simulator", "evidence") for f in manifest["source_files"])  # UI and analysis layers are not frozen


# ---------------------------------------------------------------- run preconditions
def _git_factory(tree_clean: bool = True, head: str = "aaa", run_tag: str = "aaa", freeze_ancestor: bool = True, changed: str = "config/evaluation.json"):
    def git(root: Path, *args: str) -> str:
        if args[:2] == ("status", "--porcelain"):
            return "" if tree_clean else " M src/x.py"
        if args == ("rev-parse", "HEAD"):
            return head
        if args[0] == "rev-parse" and "holdout-run-v1" in args[1]:
            return run_tag
        if args[0] == "rev-parse" and "holdout-freeze-v1" in args[1]:
            return "fff"
        if args[0] == "merge-base":
            if not freeze_ancestor:
                raise subprocess.CalledProcessError(1, ["git", "merge-base"])
            return ""
        if args[0] == "diff":
            return changed
        raise AssertionError(args)

    return git


def _cfg(**kw):
    return replace(load_config(), **kw)


def test_preconditions_refuse_while_locked_and_list_every_problem() -> None:
    plan = load_plan(ROOT)
    problems = check_preconditions(_cfg(holdout_unlocked=False), plan, ROOT, _git_factory())
    assert any("holdout_unlocked" in p for p in problems)
    problems = check_preconditions(_cfg(holdout_unlocked=True, holdout_spent=True), plan, ROOT, _git_factory())
    assert any("already been spent" in p for p in problems)
    problems = check_preconditions(_cfg(holdout_unlocked=True), plan, ROOT, _git_factory(tree_clean=False, head="x", freeze_ancestor=False, changed="src/a.py\nconfig/evaluation.json"))
    text = " | ".join(problems)
    assert "not clean" in text and "HEAD is not the commit tagged" in text and "not an ancestor" in text and "files changed since" in text and "src/a.py" in text


def test_preconditions_allow_the_run_only_when_everything_holds(monkeypatch, tmp_path: Path) -> None:
    plan = load_plan(ROOT)
    monkeypatch.setattr(freeze, "verify", lambda root: [])
    assert check_preconditions(_cfg(holdout_unlocked=True), plan, tmp_path, _git_factory()) == []  # tmp_path: no earlier results exist
    monkeypatch.setattr(freeze, "verify", lambda root: ["source_files: src/bsp/x.py changed"])
    assert any("freeze manifest" in p for p in check_preconditions(_cfg(holdout_unlocked=True), plan, tmp_path, _git_factory()))
    monkeypatch.setattr(freeze, "verify", lambda root: [])
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "holdout.md").write_text("x")
    assert any("already exist" in p for p in check_preconditions(_cfg(holdout_unlocked=True), plan, tmp_path, _git_factory()))


def test_a_missing_tag_is_reported_not_crashed() -> None:
    def git(root: Path, *args: str) -> str:
        if args[:2] == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return "aaa"
        raise subprocess.CalledProcessError(128, ["git", "rev-parse", "holdout-run-v1^{commit}"])

    problems = check_preconditions(_cfg(holdout_unlocked=True), load_plan(ROOT), ROOT, git)
    assert any("git check failed" in p and "tag missing" in p for p in problems)


# ---------------------------------------------------------------- decision rules and plan
def test_the_plan_names_only_known_models_and_unlocked_rehearsal_budgets() -> None:
    plan = load_plan(ROOT)
    assert plan["eval_budgets"]["holdout"] == ["FY2024-25", "FY2025-26"] and not set(plan["eval_budgets"]["rehearsal"]) & LOCKED
    saved = pd.read_csv(ROOT / "reports" / "models_summary.csv")
    known = set(saved[saved["level"] == "sector"]["model"]) | set(saved[saved["level"] == "stock"]["model"])
    assert set(plan["sector_models"]) | set(plan["stock_models"]) <= known
    assert plan["primary"]["bar"] == 0.10 and plan["primary"]["model"] == "tier1_blend"


def _metrics(ic_blend: tuple[float, float], net: dict[str, tuple[float, float]]) -> pd.DataFrame:
    rows = []
    for i, b in enumerate(("B1", "B2")):
        rows.append({"level": "sector", "model": "tier1_blend", "budget_id": b, "ic": ic_blend[i], "port_net": net["blend"][i]})
        rows.append({"level": "sector", "model": "equal_weight", "budget_id": b, "ic": float("nan"), "port_net": net["eq"][i]})
        rows.append({"level": "stock", "model": "tier2_ranker", "budget_id": b, "ic": 0.05, "port_net": net["t2"][i]})
        rows.append({"level": "stock", "model": "equal_weight", "budget_id": b, "ic": float("nan"), "port_net": net["seq"][i]})
    return pd.DataFrame(rows)


def test_verdicts_apply_the_rules_mechanically() -> None:
    plan = load_plan(ROOT)
    coverage = pd.DataFrame([{"model": "tier1_blend", "level": "sector", "coverage": 0.80}])
    control = pd.DataFrame([{"model": "tier1_blend", "budget_id": "B1", "in_predicted_top3": True},
                            {"model": "tier1_blend", "budget_id": "B2", "in_predicted_top3": False}])
    good = _metrics((0.12, 0.30), {"blend": (0.2, 0.3), "eq": (0.1, 0.2), "t2": (0.3, 0.3), "seq": (0.1, 0.2)})
    v = verdicts(plan, good, coverage, control, ["B1", "B2"])
    assert v["P1"]["met"] and v["S1"]["met"] and v["S2"]["met"] and v["S3"]["met"] and v["S4"]["met"]
    bad = _metrics((0.12, 0.09), {"blend": (0.2, 0.1), "eq": (0.1, 0.2), "t2": (0.3, 0.1), "seq": (0.1, 0.2)})  # IC 0.09 < bar, loses once
    v = verdicts(plan, bad, coverage.assign(coverage=0.70), control.assign(in_predicted_top3=True), ["B1", "B2"])
    assert not v["P1"]["met"] and not v["S1"]["met"] and not v["S2"]["met"] and not v["S3"]["met"] and not v["S4"]["met"]


# ---------------------------------------------------------------- rehearsal outputs
def test_the_rehearsal_is_labelled_not_the_holdout_and_touched_no_locked_budget() -> None:
    text = (ROOT / "reports" / "holdout_rehearsal.md").read_text(encoding="utf-8")
    assert "NOT the hold-out" in text and "Drift check" in text
    for name in ("holdout_rehearsal_metrics.csv", "holdout_rehearsal_predictions.csv", "holdout_rehearsal_control_sector.csv"):
        frame = pd.read_csv(ROOT / "reports" / name)
        assert not set(frame["budget_id"]) & LOCKED and set(frame["budget_id"]) <= {"FY2022-23", "FY2023-24"}
    result = json.loads((ROOT / "reports" / "holdout_rehearsal_result.json").read_text())
    assert result["mode"] == "rehearsal" and max(result["drift"].values()) <= 1e-6  # every fold reproduces the saved Phase 5 predictions
    predictions = pd.read_csv(ROOT / "reports" / "holdout_rehearsal_predictions.csv")
    assert predictions[["p10", "p90", "top_reasons"]].notna().all().all()
    assert (predictions["top_reasons"].map(lambda s: len(json.loads(s))) == 3).all()


def test_no_holdout_result_exists_before_the_run() -> None:
    cfg = load_config()
    if cfg.holdout_spent:
        assert (ROOT / "reports" / "holdout.md").exists() and (ROOT / "reports" / "holdout_result.json").exists()
    else:
        assert not (ROOT / "reports" / "holdout.md").exists() and not (ROOT / "reports" / "holdout_result.json").exists()
