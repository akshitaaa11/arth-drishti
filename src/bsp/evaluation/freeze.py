"""Freeze manifest for the one-time hold-out run (README Phase 9).

``python -m bsp.evaluation.freeze`` writes ``config/holdout_freeze.json``: SHA-256 of every source file under ``src/bsp``, every
file in ``config/`` (``evaluation.json`` is hashed on its modelling settings only, so unlocking the hold-out does not change the
freeze), the data files the run reads, and the saved Phase 5/7 predictions used as the drift reference, plus the library versions
and the evaluation settings (seed, tuning trials, alpha grid, costs). ``verify`` recomputes it and lists every difference.
The hold-out runner refuses to run unless the manifest still matches and nothing but ``config/evaluation.json`` changed since the
freeze tag (bsp/evaluation/holdout.py).
"""

from __future__ import annotations

import hashlib
import json
import platform
from importlib import metadata
from pathlib import Path

from bsp.common.config import get_project_root

MANIFEST = "config/holdout_freeze.json"
EVALUATION_SETTING_KEYS = ["holdout_fiscal_years", "live_fiscal_years", "first_test_fiscal_year", "min_train_budgets", "top_k_sectors",
                           "top_k_stocks", "round_trip_cost", "seed", "ridge_alpha_grid", "interval_level"]
DATA_FILES = ["features_sector_year_wide.csv", "features_stock_year_wide.csv", "targets.csv", "prices_daily.csv", "index_daily.csv",
              "macro.csv", "fpi_sector_fortnightly.csv", "sector_baskets_daily.csv", "stock_first_price_date.csv"]
REFERENCE_FILES = ["reports/baselines_predictions_sector.csv", "reports/models_predictions_sector.csv", "reports/models_predictions_stock.csv",
                   "reports/predictions_detail.csv"]
LIBRARIES = ["numpy", "pandas", "scikit-learn", "scipy", "lightgbm", "pymc", "pytensor", "optuna", "shap", "mapie", "mlflow"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root: Path, pattern: str) -> dict[str, str]:
    return {str(p.relative_to(root)): _sha(p) for p in sorted(root.glob(pattern)) if p.is_file() and "__pycache__" not in p.parts}


def build_manifest(root: Path | None = None) -> dict[str, object]:
    root = root or get_project_root()
    evaluation = json.loads((root / "config" / "evaluation.json").read_text(encoding="utf-8"))
    settings = {k: evaluation[k] for k in EVALUATION_SETTING_KEYS}
    config = {k: v for k, v in _files(root, "config/*").items() if k not in ("config/evaluation.json", MANIFEST)}
    versions = {}
    for lib in LIBRARIES:
        try:
            versions[lib] = metadata.version(lib)
        except metadata.PackageNotFoundError:
            versions[lib] = "not installed"
    return {
        "note": "Frozen before the one-time hold-out run (README Phase 9). Do not edit by hand; regenerate only before the freeze tag.",
        "evaluation_settings": settings,
        "evaluation_settings_sha256": hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest(),
        "source_files": _files(root, "src/bsp/**/*.py"),
        "config_files": config,
        "data_files": {f"data/csv/{f}": _sha(root / "data" / "csv" / f) for f in DATA_FILES},
        "reference_prediction_files": {f: _sha(root / f) for f in REFERENCE_FILES},
        "libraries": versions,
        "python": platform.python_version(),
    }


def verify(root: Path | None = None) -> list[str]:
    """Differences between the committed manifest and the files now (empty list = still frozen)."""
    root = root or get_project_root()
    saved = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    now = build_manifest(root)
    problems: list[str] = []
    for section in ("source_files", "config_files", "data_files", "reference_prediction_files"):
        before, after = saved[section], now[section]
        assert isinstance(before, dict) and isinstance(after, dict)
        for name in sorted(set(before) | set(after)):
            if before.get(name) != after.get(name):
                problems.append(f"{section}: {name} {'added' if name not in before else 'removed' if name not in after else 'changed'}")
    if saved["evaluation_settings"] != now["evaluation_settings"]:
        problems.append("evaluation settings changed")
    return problems


def main() -> None:
    root = get_project_root()
    manifest = build_manifest(root)
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST}: {len(manifest['source_files'])} source files, {len(manifest['config_files'])} config files")  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
