"""Evaluation settings and the hold-out lock (README section 3, rule 5)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from bsp.common.config import get_project_root


class HoldoutLockedError(RuntimeError):
    """Raised when hold-out (or sealed live-year) rows are requested before Phase 9 unlocks them."""


@dataclass(frozen=True)
class EvalConfig:
    holdout_fiscal_years: tuple[str, ...]
    live_fiscal_years: tuple[str, ...]
    holdout_unlocked: bool
    first_test_fiscal_year: str
    min_train_budgets: int
    top_k_sectors: int
    top_k_stocks: int
    round_trip_cost: float
    seed: int
    ridge_alpha_grid: tuple[float, ...]
    interval_level: float
    root: Path = field(default_factory=get_project_root)

    @property
    def locked_fiscal_years(self) -> frozenset[str]:
        """Locked by fiscal year, so an interim budget (e.g. FY2024-25-I) is locked with its full budget."""
        return frozenset(self.holdout_fiscal_years) | frozenset(self.live_fiscal_years)

    def assert_not_locked(self, fiscal_years: object, what: str = "rows") -> None:
        """Raise unless the hold-out is unlocked or none of ``fiscal_years`` is a hold-out / live year."""
        touched = sorted(set(map(str, fiscal_years)) & self.locked_fiscal_years)  # type: ignore[call-overload]
        if touched and not self.holdout_unlocked:
            raise HoldoutLockedError(
                f"{what} for fiscal years {touched} are the locked hold-out / live years. They stay untouched until "
                'Phase 9 sets "holdout_unlocked": true in config/evaluation.json.'
            )


def load_config(project_root: Path | None = None, **overrides: object) -> EvalConfig:
    root = project_root or get_project_root()
    raw = json.loads((root / "config" / "evaluation.json").read_text(encoding="utf-8"))
    raw.update(overrides)
    return EvalConfig(
        holdout_fiscal_years=tuple(raw["holdout_fiscal_years"]),
        live_fiscal_years=tuple(raw["live_fiscal_years"]),
        holdout_unlocked=bool(raw["holdout_unlocked"]),
        first_test_fiscal_year=str(raw["first_test_fiscal_year"]),
        min_train_budgets=int(raw["min_train_budgets"]),
        top_k_sectors=int(raw["top_k_sectors"]),
        top_k_stocks=int(raw["top_k_stocks"]),
        round_trip_cost=float(raw["round_trip_cost"]),
        seed=int(raw["seed"]),
        ridge_alpha_grid=tuple(float(a) for a in raw["ridge_alpha_grid"]),
        interval_level=float(raw["interval_level"]),
        root=root,
    )
