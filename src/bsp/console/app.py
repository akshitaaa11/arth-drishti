"""Streamlit analyst console for internal checks (README Phase 10): data freshness, row counts, leakage status, model results and hold-out state.

Run: ``streamlit run src/bsp/console/app.py`` (``make console``). Read-only: it never writes data and never loads the locked hold-out.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from bsp.common.config import get_project_root

ROOT = get_project_root()
CSV = ROOT / "data" / "csv"
DISCLAIMER = "Research tool, not investment advice."


@st.cache_data(show_spinner=False)
def read(path: str) -> pd.DataFrame:
    return pd.read_csv(ROOT / path)


def freshness() -> None:
    st.subheader("Collector runs (fetch_log.csv)")
    log = read("data/csv/fetch_log.csv")
    last = log.sort_values("started_at").groupby("job").tail(1) if "started_at" in log else log.groupby("job").tail(1)
    st.dataframe(last, width="stretch", hide_index=True)
    st.caption("Latest row per job; 'blocked' or 'partial' means the source refused part of the request and the previous CSV was kept.")


def tables() -> None:
    st.subheader("Row counts and date ranges of the data CSVs")
    rows = []
    for path in sorted(CSV.glob("*.csv")):
        frame = pd.read_csv(path)
        date_col = next((c for c in ("date", "period_end", "presented_on", "as_of_date", "fetched_at") if c in frame.columns), None)
        rows.append({"file": path.name, "rows": len(frame), "columns": len(frame.columns),
                     "first": str(frame[date_col].min()) if date_col and len(frame) else "", "last": str(frame[date_col].max()) if date_col and len(frame) else ""})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def leakage() -> None:
    from bsp.quality.leakage import LeakageError, validate_feature_store

    st.subheader("Leakage checks on the feature store")
    try:
        validate_feature_store(ROOT)
        st.success("All point-in-time checks pass (dates, same-year actuals, listing, liquidity, speech features).")
    except LeakageError as exc:
        st.error(f"Leakage detected: {exc}")


def models() -> None:
    st.subheader("Walk-forward results (reports/models_summary.csv)")
    summary = read("reports/models_summary.csv")
    st.dataframe(summary[["level", "model", "ic", "top3_hit", "bt_cagr", "bt_sharpe", "bt_max_drawdown"]].round(3) if "top3_hit" in summary else summary,
                 width="stretch", hide_index=True)
    st.subheader("Predictions browser (reports/predictions_detail.csv)")
    detail = read("reports/predictions_detail.csv")
    model = st.selectbox("Model", sorted(detail["model"].unique()), index=0)
    budget = st.selectbox("Budget", sorted(detail["budget_id"].unique())[::-1])
    view = detail[(detail["model"] == model) & (detail["budget_id"] == budget)].sort_values("rank")
    st.dataframe(view[["entity", "rank", "expected_excess", "p10", "p90", "p_beat", "actual", "interval_method"]].round(4), width="stretch", hide_index=True)


def holdout() -> None:
    st.subheader("Hold-out state")
    cfg = json.loads((ROOT / "config" / "evaluation.json").read_text(encoding="utf-8"))
    st.json({k: cfg[k] for k in ("holdout_fiscal_years", "live_fiscal_years", "holdout_unlocked") if k in cfg} | {"holdout_spent": cfg.get("holdout_spent", False)})
    st.write("Hold-out result present:", (ROOT / "reports" / "holdout.md").exists())
    from bsp.evaluation import freeze

    problems = freeze.verify(ROOT) if (ROOT / freeze.MANIFEST).exists() else ["no freeze manifest"]
    st.write("Freeze manifest:", "matches the tree" if not problems else f"{len(problems)} difference(s) (expected once later phases change the code)")


def main() -> None:
    st.set_page_config(page_title="Arth Drishti console", layout="wide")
    st.title("Arth Drishti: analyst console")
    st.caption(DISCLAIMER)
    tab = st.tabs(["Freshness", "Data", "Leakage", "Models", "Hold-out"])
    with tab[0]:
        freshness()
    with tab[1]:
        tables()
    with tab[2]:
        leakage()
    with tab[3]:
        models()
    with tab[4]:
        holdout()


main()
