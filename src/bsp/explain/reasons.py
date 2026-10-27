"""Three plain-English reasons per prediction (README Phase 7, FR-10).

Input: the additive attribution of one forecast (a baseline plus one contribution per feature, on the expected-excess-return
scale, see ``contributions.py``) and the row's feature values. Output: exactly three bullets for the three features with the
largest absolute contribution (ties broken by feature name), each with the underlying number, the effect in percentage points
and a source reference from config/feature_reasons.json. A missing value is said to be missing, not shown as a number.
The baseline is never a reason. The reasons explain the expected excess return that the interval wraps; the rank comes from the
ranker, whose ordering usually but not always agrees with it.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from bsp.common.config import get_project_root

N_REASONS = 3


@lru_cache(maxsize=4)
def load_reason_config(root: Path | None = None) -> dict[str, dict[str, str]]:
    path = (root or get_project_root()) / "config" / "feature_reasons.json"
    return json.loads(path.read_text(encoding="utf-8"))["features"]  # type: ignore[no-any-return]


def format_value(value: float | None, kind: str) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "not available"
    if kind == "pct":
        return f"{value:+.1f}%"
    if kind == "frac_pct":
        return f"{value * 100:+.1f}%"
    if kind == "crore":
        return f"Rs {value:,.0f} crore"
    if kind == "rate":
        return f"{value:.2f}%"
    if kind == "flag":
        return "yes" if value >= 0.5 else "no"
    return f"{value:.2f}"


def reasons_for(contributions: Mapping[str, float], values: Mapping[str, float | None], root: Path | None = None) -> list[str]:
    """Exactly three bullets from per-feature contributions (fractions of excess return; shown as percentage points)."""
    config = load_reason_config(root)
    ranked = sorted(contributions.items(), key=lambda kv: (-abs(kv[1]), kv[0]))
    if len(ranked) < N_REASONS:
        raise ValueError(f"need at least {N_REASONS} feature contributions, got {len(ranked)}")
    bullets = []
    for name, effect in ranked[:N_REASONS]:
        meta = config.get(name, {"label": name, "format": "number", "source": "feature store"})
        shown = format_value(values.get(name), meta["format"])
        verb = "raised" if effect >= 0 else "lowered"
        subject = meta["label"][0].upper() + meta["label"][1:]
        state = "was not available" if shown == "not available" else f"is {shown}"
        bullets.append(f"{subject} {state}, which {verb} the expected excess return by {abs(effect) * 100:.1f} percentage points "
                       f"(source: {meta['source']}).")
    return bullets
