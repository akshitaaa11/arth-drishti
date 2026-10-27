"""Evidence-based handling of single-day price jumps in the daily price file.

A row is *flagged* when its close-to-close move exceeds 50% (``FLAG_THRESHOLD``). Every flag gets a
documented decision; the decisions are applied here, in the pipeline, never by editing CSVs. Rules run in
this order on each symbol, using only the downloaded prices and the downloaded split history
(``data/raw/yahoo_actions/<symbol>_actions.csv``):

1. ``placeholder``: ``volume == 0`` and open == high == low == close. A run of such rows at the *start* of a
   series (before the first real trade) is padding, not trading, and is dropped; so is a placeholder that is
   itself flagged or sits directly before a flagged row.
2. ``bad_close``: close outside [low, high] by more than 0.5% - the close field is corrupt. Dropped.
3. ``spike_reversal``: the row is out of line with both neighbours, which agree with each other within 25%.
   A one-day outlier (e.g. one day printed on a different split scale). Dropped.
4. ``split_discontinuity``: a split listed in the downloaded split history within 3 trading days of the
   flag, whose ratio matches the observed jump within 10%. Prices before the date are rescaled by the
   split ratio so the series is continuous (volume inversely).
5. Anything else is kept with cause ``unexplained`` and decision ``keep`` ("unexplained, kept" in the evidence): a
   persistent level shift with normal volume that no downloaded source explains (e.g. a demerger or capital
   reduction). It stays in the data and is listed for manual review against NSE corporate actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

FLAG_THRESHOLD = 0.5
CLOSE_TOLERANCE = 0.005
SPIKE_NEIGHBOUR_TOLERANCE = 0.25
SPLIT_MATCH_TOLERANCE = 0.10
SPLIT_WINDOW_DAYS = 3
PRICE_COLUMNS = ["open", "high", "low", "close", "adj_close"]


@dataclass
class CleaningResult:
    prices: pd.DataFrame
    decisions: pd.DataFrame  # one row per original flag
    dropped: pd.DataFrame  # every row removed, with the rule that removed it
    adjustments: pd.DataFrame  # every split rescaling applied


def flag_jumps(prices: pd.DataFrame, threshold: float = FLAG_THRESHOLD) -> pd.DataFrame:
    ordered = prices.sort_values(["symbol", "date"]).copy()
    ordered["ret"] = ordered.groupby("symbol")["close"].pct_change()
    mask = (ordered["ret"].abs() > threshold) | (ordered["close"] <= 0) | (ordered["volume"] < 0)
    return ordered[mask]


def _placeholder(frame: pd.DataFrame) -> pd.Series:
    return (
        (frame["volume"] == 0)
        & (frame["open"] == frame["high"])
        & (frame["high"] == frame["low"])
        & (frame["low"] == frame["close"])
    )


def _bad_close(frame: pd.DataFrame) -> pd.Series:
    return (frame["close"] > frame["high"] * (1 + CLOSE_TOLERANCE)) | (
        frame["close"] < frame["low"] * (1 - CLOSE_TOLERANCE)
    )


def _leading_placeholder_run(frame: pd.DataFrame) -> pd.Series:
    """True for the unbroken run of placeholder rows at the start of a symbol's series."""
    ph = _placeholder(frame).to_numpy()
    out = np.zeros(len(frame), dtype=bool)
    for i, is_ph in enumerate(ph):
        if not is_ph:
            break
        out[i] = True
    return pd.Series(out, index=frame.index)


def _splits_for(splits: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if splits is None or splits.empty:
        return pd.DataFrame(columns=["symbol", "date", "ratio"])
    sub = splits[splits["symbol"] == symbol].copy()
    sub["ratio"] = pd.to_numeric(sub["ratio"], errors="coerce")
    return sub.dropna(subset=["ratio"])


def clean_prices(prices: pd.DataFrame, splits: pd.DataFrame | None = None) -> CleaningResult:
    """Apply the documented rules to ``prices`` (columns incl. symbol, date, OHLC, adj_close, volume)."""
    frame = prices.assign(date=prices["date"].astype(str)).sort_values(["symbol", "date"]).reset_index(drop=True)
    original_flags = flag_jumps(frame)
    dropped: list[dict[str, object]] = []
    adjustments: list[dict[str, object]] = []
    cleaned_groups: list[pd.DataFrame] = []
    splits = splits if splits is not None else pd.DataFrame(columns=["symbol", "date", "ratio"])

    for symbol, group in frame.groupby("symbol", sort=True):
        g = group.reset_index(drop=True)
        g_flagged = set(flag_jumps(g)["date"])

        # Rule 1: leading placeholder padding, and placeholders that are flagged / precede a flagged row.
        lead = _leading_placeholder_run(g)
        ph = _placeholder(g)
        next_flagged = g["date"].shift(-1).isin(g_flagged)
        rule1 = lead | (ph & (g["date"].isin(g_flagged) | next_flagged))
        # Rule 2: corrupt close.
        rule2 = _bad_close(g) & ~rule1
        for rule, mask in (("placeholder", rule1), ("bad_close", rule2)):
            for _, row in g[mask].iterrows():
                dropped.append({"symbol": symbol, "date": row["date"], "rule": rule, "close": row["close"],
                                "volume": row["volume"]})
        g = g[~(rule1 | rule2)].reset_index(drop=True)

        # Rule 3: one-day outliers, re-evaluated after each drop so adjacent bad rows resolve in order.
        changed = True
        while changed:
            changed = False
            close = g["close"].to_numpy()
            for i in range(1, len(g) - 1):
                prev_c, cur, nxt = close[i - 1], close[i], close[i + 1]
                if prev_c <= 0 or nxt <= 0:
                    continue
                neighbours_agree = abs(nxt / prev_c - 1) < SPIKE_NEIGHBOUR_TOLERANCE
                out_of_line = abs(cur / prev_c - 1) > FLAG_THRESHOLD or abs(cur / nxt - 1) > FLAG_THRESHOLD
                if neighbours_agree and out_of_line:
                    row = g.iloc[i]
                    dropped.append({"symbol": symbol, "date": row["date"], "rule": "spike_reversal",
                                    "close": row["close"], "volume": row["volume"]})
                    g = g.drop(g.index[i]).reset_index(drop=True)
                    changed = True
                    break

        # Rule 4: discontinuities explained by a downloaded split.
        sym_splits = _splits_for(splits, str(symbol))
        remaining = flag_jumps(g)
        for _, row in remaining.iterrows():
            idx = g.index[g["date"] == row["date"]][0]
            lo, hi = max(0, idx - SPLIT_WINDOW_DAYS), min(len(g) - 1, idx + SPLIT_WINDOW_DAYS)
            window = set(g.loc[lo:hi, "date"])
            near = sym_splits[sym_splits["date"].isin(window)]
            observed = g.loc[idx, "close"] / g.loc[idx - 1, "close"] if idx > 0 else np.nan
            for split in near.itertuples():
                ratio = cast(float, split.ratio)
                # A split of ratio s multiplies the share count by s, so the price should fall by 1/s; the
                # discontinuity may point either way when the source adjusted only part of the history.
                if not any(abs(observed * f - 1) < SPLIT_MATCH_TOLERANCE for f in (ratio, 1 / ratio)):
                    continue
                before = g["date"] < row["date"]
                g["volume"] = g["volume"].astype(float)
                g.loc[before, PRICE_COLUMNS] = g.loc[before, PRICE_COLUMNS] * observed  # make history continuous
                g.loc[before, "volume"] = g.loc[before, "volume"] / observed
                adjustments.append({"symbol": symbol, "date": row["date"], "split_date": split.date,
                                    "split_ratio": ratio, "observed_jump": observed, "scale_applied": observed})
                break
        cleaned_groups.append(g)

    cleaned = pd.concat(cleaned_groups, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)
    dropped_df = pd.DataFrame(dropped, columns=["symbol", "date", "rule", "close", "volume"])
    adjust_df = pd.DataFrame(adjustments, columns=["symbol", "date", "split_date", "split_ratio",
                                                   "observed_jump", "scale_applied"])
    decisions_df = _decide(original_flags, cleaned, dropped_df, adjust_df)
    return CleaningResult(cleaned, decisions_df, dropped_df, adjust_df)


def _decide(flags: pd.DataFrame, cleaned: pd.DataFrame, dropped: pd.DataFrame, adjust: pd.DataFrame) -> pd.DataFrame:
    """One documented decision per original flag."""
    out: list[dict[str, object]] = []
    dropped_idx = {(r.symbol, r.date): r for r in dropped.itertuples()}
    adjust_idx = {(r.symbol, r.date): r for r in adjust.itertuples()}
    residual = {(r.symbol, r.date) for r in flag_jumps(cleaned).itertuples()}
    for row in flags.itertuples():
        key = (row.symbol, row.date)
        jump = round(cast(float, row.ret) * 100, 2) if pd.notna(row.ret) else None
        base = {"symbol": row.symbol, "date": row.date, "jump_pct": jump}
        if key in dropped_idx:
            d = dropped_idx[key]
            cause, decision, evidence = {
                "placeholder": ("data error", "drop",
                                f"volume=0 and open=high=low=close={d.close:.4g}: non-trading placeholder row, "
                                "not a trade; the neighbouring real prices are on a different level"),
                "bad_close": ("data error", "drop",
                              f"close {d.close:.4g} lies outside the same-day [low, high] range"),
                "spike_reversal": ("data error", "drop",
                                   f"close {d.close:.4g} is out of line with both neighbouring days, which agree "
                                   "within 25% of each other (one-day outlier)"),
            }[str(d.rule)]
        elif key in adjust_idx:
            a = adjust_idx[key]
            cause, decision = "split", "adjust"
            evidence = (f"downloaded split history lists a {a.split_ratio:g}:1 split on {a.split_date}; observed "
                        f"close ratio {a.observed_jump:.3f}; earlier prices rescaled by {a.scale_applied:.4f}")
        elif key in residual:
            cause, decision = "unexplained", "keep"
            evidence = ("unexplained, kept: no data defect found (volume non-zero, close inside high-low range, not a "
                        "one-day outlier) and no downloaded split explains it; it may be a real corporate action "
                        "(demerger, capital reduction) - confirm against NSE corporate actions (manual review)")
        else:
            earlier = dropped[(dropped["symbol"] == row.symbol) & (dropped["date"] < row.date)]
            via = f" ({earlier.iloc[-1]['rule']} on {earlier.iloc[-1]['date']})" if len(earlier) else ""
            cause, decision = "data error", "keep"
            evidence = (f"the move was measured against an earlier row that the pipeline dropped{via}; after "
                        "cleaning, this row follows its real predecessor and the jump no longer exists")
        out.append({**base, "likely_cause": cause, "decision": decision, "evidence": evidence})
    return pd.DataFrame(out, columns=["symbol", "date", "jump_pct", "likely_cause", "decision", "evidence"])


def write_reports(result: CleaningResult, reports_dir: Path) -> None:
    """Write the decision, dropped-row and split-adjustment reports for one cleaning run."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    result.decisions.to_csv(reports_dir / "price_flag_decisions.csv", index=False)
    result.dropped.to_csv(reports_dir / "price_rows_dropped.csv", index=False)
    result.adjustments.to_csv(reports_dir / "price_split_adjustments.csv", index=False)


def main() -> None:
    """Rebuild the three decision reports from the saved raw download, without any network access.

    Reads ``data/raw/yahoo_prices/prices_raw.csv`` and ``data/raw/yahoo_actions/*_splits.csv`` (both written by
    ``bsp.ingest.prices``) and applies the same rules the price job applies; ``prices_daily.csv`` is not touched.
    """
    import glob

    root = Path(__file__).resolve().parents[3]
    raw = pd.read_csv(root / "data" / "raw" / "yahoo_prices" / "prices_raw.csv")
    files = sorted(glob.glob(str(root / "data" / "raw" / "yahoo_actions" / "*_splits.csv")))
    splits = pd.concat([pd.read_csv(f) for f in files], ignore_index=True) if files else None
    result = clean_prices(raw, splits)
    write_reports(result, root / "reports")
    counts = result.decisions.groupby(["likely_cause", "decision"]).size().to_dict()
    print(f"{len(result.decisions)} flags decided: {counts}")


if __name__ == "__main__":
    main()
