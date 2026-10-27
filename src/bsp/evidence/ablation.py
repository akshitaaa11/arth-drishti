"""Feature-family ablations (README Phase 8): refit the walk-forward without one family and measure the drop in IC.

For each model (ridge, the LightGBM ranker) the walk-forward of Phase 4/5 is repeated with the same folds, settings and tuning
(ridge alpha grid; Optuna with the same seeded trials inside every fold) on a feature subset:
  full                     the Phase 5 sector features (identical to the reported Phase 4/5 model)
  no_<family>              full without one family (families in config/feature_families.json)
  price_only / budget_only / price_plus_budget / momentum_only   the groups of that file
  full_seed<k>             the full model with another seed: the noise floor of the LightGBM ranker (seed changes tree sampling)
The 14 budget-sensitive sectors define the IC; the control sector is predicted but not scored. A family with no data in the panel
(speech_nlp: no speeches exist) cannot be ablated and is reported as untestable. Nothing is tuned on the hold-out.

Output: ``reports/ablation_per_year.csv`` (one row per model, variant and test budget). ``python -m bsp.evidence.ablation --model ridge``
or ``--model lgbm_ranker`` (the slow one, about a minute per variant).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from bsp.evaluation.data import Panel
from bsp.evaluation.run_baselines import evaluate_predictions
from bsp.evaluation.walk_forward import Model, stack_predictions, walk_forward
from bsp.evidence.context import Context, load_context
from bsp.models.baselines import RidgeBaseline, make_ridge_tuner
from bsp.models.ranker import LGBMRankerModel, make_ranker_tuner

NOISE_SEEDS = (1, 2, 3)
N_TRIALS = 15


def load_families(root: Path) -> dict[str, Any]:
    return json.loads((root / "config" / "feature_families.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def variant_features(panel_features: list[str], families: dict[str, Any]) -> dict[str, list[str]]:
    """Variant name -> feature list (the panel's own order). Variants whose features are all absent are kept with an empty list."""
    fam = {name: [f for f in feats if f in panel_features] for name, feats in families["families"].items()}
    groups = {name: [f for member in members for f in fam[member]] for name, members in families["groups"].items()}
    out: dict[str, list[str]] = {"full": list(panel_features)}
    for name, feats in fam.items():
        out[f"no_{name}"] = [f for f in panel_features if f not in feats]
    for name, feats in groups.items():
        out[name] = [f for f in panel_features if f in feats]
    return out


def model_spec(name: str, ctx: Context, seed: int) -> tuple[Callable[..., Model], Any]:
    cfg = ctx.cfg
    if name == "ridge":
        return (lambda alpha=10.0: RidgeBaseline(alpha=alpha, interval_level=cfg.interval_level)), make_ridge_tuner(cfg.ridge_alpha_grid)
    if name == "lgbm_ranker":
        return ((lambda **p: LGBMRankerModel(seed=seed, interval_level=cfg.interval_level, **p)),
                make_ranker_tuner(n_trials=N_TRIALS, seed=seed))
    raise ValueError(f"unknown model {name}")


def run_variant(model: str, variant: str, features: list[str], ctx: Context, seed: int) -> pd.DataFrame:
    factory, tune = model_spec(model, ctx, seed)
    panel = Panel(ctx.panel.kind, ctx.panel.frame, features)
    folds = walk_forward(panel, factory, ctx.cfg, tune)
    run = evaluate_predictions(f"{model}/{variant}", stack_predictions(folds), False, {}, ctx.cfg, ctx.windows, ctx.bundle, ctx.bench)
    frame = run.per_year[["budget_id", "ic", "top3_hit", "port_net", "bench_net", "port_excess"]].copy()
    frame.insert(0, "n_features", len(features))
    frame.insert(0, "variant", variant)
    frame.insert(0, "model", model)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=["ridge", "lgbm_ranker"], required=True)
    args = parser.parse_args()
    ctx = load_context()
    families = load_families(ctx.cfg.root)
    variants = variant_features(ctx.panel.features, families)
    frames = []
    for variant, features in variants.items():
        if not features or (variant.startswith("no_") and features == variants["full"]):
            print(f"skip {variant}: nothing to remove or no features")
            continue
        print(f"{args.model}: {variant} ({len(features)} features)", flush=True)
        frames.append(run_variant(args.model, variant, features, ctx, ctx.cfg.seed))
    if args.model == "lgbm_ranker":
        for seed in NOISE_SEEDS:
            print(f"{args.model}: full_seed{seed}", flush=True)
            frames.append(run_variant(args.model, f"full_seed{seed}", variants["full"], ctx, seed))
    path = ctx.cfg.root / "reports" / f"ablation_per_year_{args.model}.csv"
    pd.concat(frames, ignore_index=True).round(8).to_csv(path, index=False)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
