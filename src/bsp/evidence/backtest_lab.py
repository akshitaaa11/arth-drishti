"""F12 backtest lab: "follow the model since FY2012-13" against the Nifty 500 and the baselines, net of costs.

Rebuilt from the saved out-of-sample predictions (``reports/baselines_predictions_sector.csv``,
``reports/models_predictions_sector.csv``, ``reports/models_predictions_stock.csv``) with the same selection rule, windows and
cost model as Phase 4/5 (top-3 sectors or top-15 stocks, equal weight, 0.2% round trip). No model is refitted. Sector baskets are
equal-weight baskets of today's stocks and the stock list has survivorship bias (reports/data_gaps.md), so every portfolio tends
to beat the cap-weighted Nifty 500 and the fair bar is the equal-weight row.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bsp.evaluation.backtest import BacktestResult, run_backtest, top_k_selection
from bsp.evaluation.run_baselines import BENCHMARK
from bsp.evidence.context import Context

SECTOR_MODELS = ["equal_weight", "last_years_winners", "biggest_allocation_increase", "ridge", "lgbm_ranker", "bayes_hier", "tier1_blend", "tier1_stack"]
STOCK_MODELS = ["equal_weight", "momentum_12m", "ridge", "sector_then_momentum", "tier2_ranker"]
COSTS = (0.0, 0.002, 0.005)


def load_sector_predictions(root: Path) -> pd.DataFrame:
    base = pd.read_csv(root / "reports" / "baselines_predictions_sector.csv")
    new = pd.read_csv(root / "reports" / "models_predictions_sector.csv")
    return pd.concat([base, new[~new["model"].isin(base["model"])]], ignore_index=True)


def backtest_model(predictions: pd.DataFrame, model: str, k: int, levels: pd.DataFrame, ctx: Context, cost: float) -> BacktestResult:
    frame = predictions[(predictions["model"] == model) & (~predictions["is_control"].astype(bool))]
    selections = top_k_selection(frame, k, model == "equal_weight")
    return run_backtest(selections, ctx.windows[ctx.windows["budget_id"].isin(selections)], levels, cost)


def run_lab(ctx: Context, root: Path) -> dict[str, tuple[pd.DataFrame, pd.DataFrame, dict[str, BacktestResult]]]:
    cfg = ctx.cfg
    sector = load_sector_predictions(root)
    stock = pd.read_csv(root / "reports" / "models_predictions_stock.csv")
    sector_levels = (1.0 + ctx.bundle.sector_returns.fillna(0.0)).cumprod()
    stock_levels = (1.0 + ctx.bundle.stock_returns.fillna(0.0)).cumprod()
    out: dict[str, tuple[pd.DataFrame, pd.DataFrame, dict[str, BacktestResult]]] = {}
    for level, preds, models, k, levels in (("sector", sector, SECTOR_MODELS, cfg.top_k_sectors, sector_levels),
                                           ("stock", stock, STOCK_MODELS, cfg.top_k_stocks, stock_levels)):
        budgets = sorted(preds["budget_id"].unique())
        bench = run_backtest({b: [BENCHMARK] for b in budgets}, ctx.windows[ctx.windows["budget_id"].isin(budgets)],
                             ctx.market_level, cfg.round_trip_cost)
        runs = {m: backtest_model(preds, m, k, levels, ctx, cfg.round_trip_cost) for m in models if m in set(preds["model"])}
        runs[BENCHMARK] = bench
        equity = pd.DataFrame({m: 100.0 * (1.0 + r.daily).cumprod() for m, r in runs.items()})
        rows = []
        for m, r in runs.items():
            s = r.summary
            sensitivity = {f"cagr_cost_{c * 100:.1f}pct": backtest_model(preds, m, k, levels, ctx, c).summary.get("cagr", float("nan"))
                           for c in COSTS} if m != BENCHMARK else {}
            rows.append({"level": level, "strategy": m, "first_window": r.periods["start"].iloc[0], "last_window": r.periods["end"].iloc[-1],
                         "n_windows": int(s["n_periods"]), "cagr": s["cagr"], "sharpe": s["sharpe"], "max_drawdown": s["max_drawdown"],
                         "turnover": s["turnover"], "total_return": s["total_return"], "final_value_of_100": float(equity[m].iloc[-1]), **sensitivity})
        out[level] = (pd.DataFrame(rows), equity, runs)
    return out


def plot_lab(equity: pd.DataFrame, path: Path, title: str, highlight: list[str]) -> None:
    """Equity curve (log scale, start = 100) over the drawdown of the highlighted strategies; direct labels at the line ends."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colours = {BENCHMARK: "#6b6a66", highlight[0]: "#2a78d6", highlight[1]: "#eb6834", highlight[2]: "#1baf7a", highlight[3]: "#eda100"}
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]}, facecolor="#fcfcfb")
    index = pd.to_datetime(equity.index)
    for name in [BENCHMARK, *highlight]:
        series = equity[name]
        top.plot(index, series, color=colours[name], linewidth=2.0 if name != BENCHMARK else 1.6, linestyle="-" if name != BENCHMARK else "--", label=name)
        bottom.plot(index, series / series.cummax() - 1.0, color=colours[name], linewidth=1.4, linestyle="-" if name != BENCHMARK else "--")
        top.annotate(f"{name}  {series.iloc[-1]:,.0f}", (index[-1], series.iloc[-1]), xytext=(6, 0), textcoords="offset points",
                     color="#0b0b0b", fontsize=8, va="center")
    top.set_yscale("log")
    top.set_ylabel("Value of 100 invested (log scale)")
    top.set_title(title, loc="left", fontsize=11, color="#0b0b0b")
    top.legend(loc="upper left", frameon=False, fontsize=8)
    bottom.set_ylabel("Drawdown")
    bottom.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    for ax in (top, bottom):
        ax.set_facecolor("#fcfcfb")
        ax.grid(color="#e4e3df", linewidth=0.6)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.subplots_adjust(right=0.8)
    fig.savefig(path, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)
