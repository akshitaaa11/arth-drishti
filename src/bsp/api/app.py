"""FastAPI application (README Phase 10, FR-12): REST endpoints over the committed CSVs, with a response cache and the what-if engine.

Run: ``uvicorn bsp.api.app:app`` (``make api``); OpenAPI docs at ``/docs``; the dashboard is served at ``/app`` when ``web/dist`` is built.
Every response that carries a number carries a ``source_ref`` resolvable at ``/sources/{ref}``. Not built (and said so in the responses):
the sealed-prediction ledger (Phase 12), CGA monthly execution (D6), order-win flags (D13), live forecasts (the live year is sealed).
The locked hold-out is never read: its budgets are listed with status ``holdout_locked`` and no forecasts.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bsp.api.cache import Cache, make_cache
from bsp.api.store import (
    PRIMARY_SECTOR_MODEL,
    PRIMARY_STOCK_MODEL,
    WINDOW_ORDER,
    Store,
    clean,
    records,
)
from bsp.common.config import get_project_root
from bsp.simulator.engine import SimulationError, Simulator

DISCLAIMER = "Research tool, not investment advice."
TTL = 300
SECTOR_MODELS = ("tier1_blend", "tier1_stack", "lgbm_ranker", "bayes_hier")


class AskRequest(BaseModel):
    question: str = Field(max_length=600, examples=["How much was the Defence ministry's budget estimate for 2019-20?"])


class SimulateRequest(BaseModel):
    budget_id: str = Field(examples=["FY2019-20"])
    changes: dict[str, float] = Field(default_factory=dict, description="sector_id -> percentage change of that sector's allocation (-100..100)")
    preset: str | None = Field(default=None, description="actual | flat_vs_re | replay:<budget_id>")


def create_app(root: Path | None = None, cache: Cache | None = None) -> FastAPI:
    root = root or get_project_root()
    store = Store(root)
    cache = cache if cache is not None else make_cache()
    app = FastAPI(title="Arth Drishti API", version="0.1.0", description=f"Budget-based sector and stock forecasts. {DISCLAIMER}")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET", "POST"], allow_headers=["*"])
    app.state.store, app.state.cache = store, cache
    sim_lock = threading.Lock()
    app.state.simulator = None

    def simulator() -> Simulator:
        with sim_lock:
            if app.state.simulator is None:
                app.state.simulator = Simulator(root)
            return app.state.simulator  # type: ignore[no-any-return]

    def respond(key: str, compute: Any, response: Response, ttl: int = TTL) -> Any:
        value, hit = cache.get_or_set(key, ttl, compute)
        response.headers["X-Cache"] = "hit" if hit else "miss"
        return value

    def need_budget(budget_id: str) -> dict[str, Any]:
        b = store.budget(budget_id)
        if b is None:
            raise HTTPException(404, f"unknown budget {budget_id!r}")
        return b

    def forecast_note(b: dict[str, Any]) -> str | None:
        return {"holdout_locked": "The FY2024-25 / FY2025-26 hold-out is locked until the one-time Phase 9 run; no forecast is shown.",
                "holdout_evaluated": "Hold-out budget: see /backtest for the one-time evaluation.",
                "live_sealed": "The live-year forecast is not produced yet (sealing is Phase 12).",
                "interim_not_modelled": "Interim budgets are not modelled."}.get(b["status"])

    @app.get("/", include_in_schema=False)
    def root_info() -> dict[str, str]:
        return {"name": "Arth Drishti API", "docs": "/docs", "dashboard": "/app/", "disclaimer": DISCLAIMER}

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "disclaimer": DISCLAIMER, "cache": type(cache).__name__, "holdout_unlocked": bool(store.evaluation["holdout_unlocked"]),
                "holdout_spent": bool(store.evaluation.get("holdout_spent"))}

    @app.get("/budgets")
    def budgets(response: Response) -> Any:
        return respond("budgets", lambda: {"budgets": store.budgets(), "latest_forecast_budget": store.latest_forecast_budget(), "disclaimer": DISCLAIMER}, response)

    @app.get("/budgets/{budget_id}/lines")
    def budget_lines(budget_id: str, response: Response, kind: str = Query("ministry", pattern="^(ministry|scheme|fiscal|demand)$")) -> Any:
        b = need_budget(budget_id)

        def compute() -> Any:
            items = store.lines(budget_id, kind)
            note = None if items else ("Budget line tables are parsed only for FY2017-18 onward (PRS analyses) and Expenditure Budget demands for FY2015-16 onward; "
                                       "earlier years are not collected yet.")
            return clean({"budget_id": budget_id, "fiscal_year": b["fiscal_year"], "kind": kind, "available": bool(items), "note": note, "items": items,
                          "takeaway": _lines_takeaway(items, kind)})
        return respond(f"lines:{budget_id}:{kind}", compute, response)

    @app.get("/sectors")
    def sectors(response: Response) -> Any:
        def compute() -> Any:
            latest = store.latest_forecast_budget()
            f = store.forecasts(latest, "sector", PRIMARY_SECTOR_MODEL).set_index("entity")
            out = []
            for s in store.sector_map:
                row = f.loc[s["sector_id"]] if s["sector_id"] in f.index else None
                out.append({"sector_id": s["sector_id"], "name": s["name"], "is_control": bool(s.get("is_control")), "budget_lines": s["budget_lines"],
                            "nsdl_fpi_sector": s.get("nsdl_fpi_sector"), "n_stocks": len(s["stocks"]),
                            "latest_rank": int(row["rank"]) if row is not None else None,
                            "latest_expected_excess": clean(row["expected_excess"]) if row is not None else None})
            return {"latest_forecast_budget": latest, "model": PRIMARY_SECTOR_MODEL, "sectors": out}
        return respond("sectors", compute, response)

    @app.get("/budgets/{budget_id}/forecast")
    def budget_forecast(budget_id: str, response: Response, model: str = Query(PRIMARY_SECTOR_MODEL)) -> Any:
        b = need_budget(budget_id)
        if model not in SECTOR_MODELS:
            raise HTTPException(422, f"model must be one of {', '.join(SECTOR_MODELS)}")

        def compute() -> Any:
            frame = store.forecasts(budget_id, "sector", model)
            rows = [store.forecast_row(r) for _, r in frame.iterrows()]
            return clean({"budget_id": budget_id, "model": model, "status": b["status"], "note": forecast_note(b), "sectors": rows, "disclaimer": DISCLAIMER,
                          "takeaway": _heatmap_takeaway(rows, budget_id), "out_of_sample": bool(rows),
                          "interval": "80% walk-forward conformal interval (p10 to p90); P(beat) is a normal approximation, see reports/explainability.md"})
        return respond(f"forecast:{budget_id}:{model}", compute, response)

    @app.get("/sectors/{sector_id}/forecast")
    def sector_forecast(sector_id: str, response: Response, budget_id: str | None = None, model: str = Query(PRIMARY_SECTOR_MODEL)) -> Any:
        info = store.sector_info(sector_id)
        if info is None:
            raise HTTPException(404, f"unknown sector {sector_id!r}")
        budget_id = budget_id or store.latest_forecast_budget()
        b = need_budget(budget_id)

        def compute() -> Any:
            frame = store.forecasts(budget_id, "sector", model)
            frame = frame[frame["entity"] == sector_id]
            if frame.empty:
                return None
            row = store.forecast_row(frame.iloc[0])
            panel = store.table("sector_budget_panel")
            p = panel[(panel["sector_id"] == sector_id) & (panel["budget_year"] == b["fiscal_year"])]
            cards: dict[str, Any] = {}
            if len(p):
                r = p.iloc[0]
                cards = {"surprise": {"value_pct": r["surprise_vs_prev_re_pct"], "be_current_cr": r["be_current_cr"], "re_previous_cr": r["re_previous_cr"],
                                      "source_ref": f"sector_budget_panel:{int(r['_row'])}"},
                         "credibility": {"value_pct": r["credibility_pct"], "years_used": r["credibility_years_used"], "source_ref": f"sector_budget_panel:{int(r['_row'])}"}}
            history = store.table("predictions_detail")
            history = history[(history["entity"] == sector_id) & (history["model"] == model) & (history["level"] == "sector")].merge(
                store.events[["budget_id", "presented_on"]], on="budget_id").sort_values("presented_on")
            return clean({"sector": {"sector_id": sector_id, "name": info["name"], "is_control": bool(info.get("is_control")), "budget_lines": info["budget_lines"]},
                          "forecast": row, "shap": store.shap_for(budget_id, sector_id, model if model in ("lgbm_ranker", "bayes_hier", "tier1_blend", "tier1_stack") else PRIMARY_SECTOR_MODEL),
                          "cards": cards, "history": records(history[["budget_id", "expected_excess", "p10", "p90", "actual", "rank"]]),
                          "takeaway": _sector_takeaway(info["name"], row, budget_id), "disclaimer": DISCLAIMER})
        value = respond(f"sector_forecast:{sector_id}:{budget_id}:{model}", compute, response)
        if value is None:
            raise HTTPException(404, forecast_note(b) or f"no forecast for {sector_id} at {budget_id}")
        return value

    @app.get("/sectors/{sector_id}/event-study")
    def event_study(sector_id: str, response: Response, budget_id: str | None = None) -> Any:
        info = store.sector_info(sector_id)
        if info is None:
            raise HTTPException(404, f"unknown sector {sector_id!r}")
        budget_id = budget_id or store.latest_forecast_budget()
        b = need_budget(budget_id)
        if b["status"] in ("holdout_locked", "live_sealed"):
            raise HTTPException(404, forecast_note(b))

        def compute() -> Any:
            es = store.table("event_study")
            es = es[(es["entity_type"] == "sector") & (es["entity"] == sector_id)]
            allowed = {x["budget_id"] for x in store.budgets() if x["status"] == "walk_forward_test"}
            this = es[es["budget_id"] == budget_id].set_index("window")
            avg = es[es["budget_id"].isin(allowed)].groupby("window")["car"].agg(["mean", "count"])
            curve = [{"window": w, "car": clean(this["car"].get(w)), "t_stat": clean(this["t_stat"].get(w)), "mean_car_all_budgets": clean(avg["mean"].get(w)),
                      "n_budgets": int(avg["count"].get(w, 0)), "source_ref": (f"event_study:{int(this['_row'].loc[w])}" if w in this.index else None)} for w in WINDOW_ORDER]
            fpi = store.table("fpi_sector_fortnightly")
            nsdl = info.get("nsdl_fpi_sector")
            day = pd.Timestamp(b["presented_on"])
            f = fpi[(fpi["nsdl_sector"] == nsdl) & (pd.to_datetime(fpi["period_end"]).between(day - pd.Timedelta(days=90), day + pd.Timedelta(days=90)))]
            strip = [{"period_end": r["period_end"], "equity_net_cr": clean(r["equity_net_cr"]), "source_ref": f"fpi_sector_fortnightly:{int(r['_row'])}",
                      "after_budget": bool(pd.Timestamp(r["period_end"]) > day)} for r in f.sort_values("period_end").to_dict("records")]
            return clean({"sector_id": sector_id, "budget_id": budget_id, "curve": curve, "fpi_strip": strip, "fpi_sector": nsdl,
                          "fpi_note": None if strip else "No NSDL FPI reports were collected around this budget (data starts 2018-09; many fortnights are missing).",
                          "takeaway": _event_takeaway(info["name"], curve, budget_id), "disclaimer": DISCLAIMER})
        return respond(f"event:{sector_id}:{budget_id}", compute, response)

    @app.get("/stocks")
    def stocks(response: Response, budget_id: str | None = None, sector: str | None = None, risk: str | None = Query(None, pattern="^(low|medium|high)$")) -> Any:
        budget_id = budget_id or store.latest_forecast_budget()
        b = need_budget(budget_id)

        def compute() -> Any:
            rows = _stock_rows(store, budget_id)
            return clean({"budget_id": budget_id, "model": PRIMARY_STOCK_MODEL, "status": b["status"], "note": forecast_note(b), "stocks": rows,
                          "order_win_flag": "not available: the order-win extractor (D13) is not built", "disclaimer": DISCLAIMER,
                          "survivorship": "The stock list is today's symbols; survivorship bias is not removed."})
        data = respond(f"stocks:{budget_id}", compute, response)
        rows = [r for r in data["stocks"] if (sector is None or r["sector_id"] == sector) and (risk is None or r["risk"] == risk)]
        return {**data, "stocks": rows, "takeaway": _stock_takeaway(rows, budget_id)}

    @app.get("/stocks/{symbol}")
    def stock(symbol: str, response: Response, budget_id: str | None = None) -> Any:
        budget_id = budget_id or store.latest_forecast_budget()
        need_budget(budget_id)
        rows = _stock_rows(store, budget_id)
        found = next((r for r in rows if r["symbol"] == symbol.upper()), None)
        if found is None:
            raise HTTPException(404, f"{symbol} is not in the model universe for {budget_id} (listing-date and liquidity rule)")
        history = store.table("predictions_detail")
        history = history[(history["entity"] == symbol.upper()) & (history["level"] == "stock")]
        return clean({"stock": found, "history": records(history[["budget_id", "expected_excess", "p10", "p90", "actual", "rank"]]), "disclaimer": DISCLAIMER})

    @app.get("/backtest")
    def backtest(response: Response) -> Any:
        return respond("backtest", lambda: _backtest(store, root), response, ttl=900)

    @app.get("/simulate/presets")
    def presets() -> Any:
        return {"presets": simulator().presets(), "sectors": [{"sector_id": s["sector_id"], "name": s["name"], "budget_lines": s["budget_lines"]} for s in store.sector_map]}

    @app.post("/simulate")
    def simulate(body: SimulateRequest) -> Any:
        try:
            return clean(simulator().run(body.budget_id, body.changes, body.preset))
        except SimulationError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/credibility")
    def credibility(response: Response) -> Any:
        return respond("credibility", lambda: _credibility(store), response)

    copilot_lock = threading.Lock()
    app.state.copilot = None

    def copilot() -> Any:
        from bsp.copilot.engine import Copilot

        with copilot_lock:
            if app.state.copilot is None:
                app.state.copilot = Copilot(store, cache=cache)
            return app.state.copilot

    @app.get("/copilot/status")
    def copilot_status() -> Any:
        return copilot().status()

    @app.post("/copilot/ask")
    def copilot_ask(req: AskRequest) -> Any:
        """Single-turn question: no history is read or stored. Guardrails, tools, number and citation checks run in ``bsp.copilot.engine``."""
        return copilot().ask(req.question)

    @app.get("/ledger")
    def ledger() -> Any:
        return {"entries": [], "note": "The sealed-prediction ledger is not built yet (Phase 12): no forecast has been sealed, so there are no hashes to show.", "disclaimer": DISCLAIMER}

    @app.get("/sources/{ref}")
    def sources(ref: str) -> Any:
        row = store.source_row(ref)
        if row is None:
            raise HTTPException(404, f"unknown source reference {ref!r}; expected <dataset>:<row>")
        doc = (row["provenance"] or {}).get("source_doc")
        pdf = root / "data" / "source_pdfs" / str(doc) if doc else None
        row["pdf_available"] = bool(pdf and pdf.is_file())
        row["pdf_url"] = f"/sources/{ref}/pdf" if row["pdf_available"] else None
        return row

    @app.get("/sources/{ref}/pdf")
    def source_pdf(ref: str) -> Any:
        row = store.source_row(ref)
        doc = ((row or {}).get("provenance") or {}).get("source_doc")
        pdf = root / "data" / "source_pdfs" / str(doc) if doc else None
        if not pdf or not pdf.is_file() or pdf.parent != root / "data" / "source_pdfs":
            raise HTTPException(404, "this source PDF is not in the repository (data/source_pdfs holds only the team's own copies)")
        return FileResponse(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{pdf.name}"'})

    @app.exception_handler(Exception)
    def unhandled(_: Any, exc: Exception) -> JSONResponse:  # pragma: no cover - last resort
        return JSONResponse({"detail": "internal error"}, status_code=500)

    dist = root / "web" / "dist"
    if dist.is_dir():
        app.mount("/app", StaticFiles(directory=dist, html=True), name="dashboard")
    return app


# ---------------------------------------------------------------------------------------------- response builders
def _lines_takeaway(items: list[dict[str, Any]], kind: str) -> str | None:
    if not items:
        return None
    if kind == "demand":
        top = max(items, key=lambda r: r["total_cr"] if r["stage"] == "BE" else -1)
        return f"{top['ministry']} has the largest budgeted demand for grants: Rs {top['total_cr']:,.0f} crore."
    be = [i for i in items if i.get("be") and i["be"].get("amount_cr") is not None]
    if not be:
        return None
    top = max(be, key=lambda i: i["be"]["amount_cr"])
    return f"{top['line_item']} is the largest {kind} line: Rs {top['be']['amount_cr']:,.0f} crore budgeted for {top['be']['fiscal_year']}."


def _heatmap_takeaway(rows: list[dict[str, Any]], budget_id: str) -> str | None:
    sensitive = [r for r in rows if not r["is_control"] and r["expected_excess"] is not None]
    if not sensitive:
        return None
    top = max(sensitive, key=lambda r: r["expected_excess"])
    return (f"For {budget_id}, the model ranked {top['sector_id']} first at {top['expected_excess'] * 100:+.1f}% expected excess return "
            f"(80% interval {top['p10'] * 100:+.0f}% to {top['p90'] * 100:+.0f}%): intervals this wide overlap for most sectors.")


def _sector_takeaway(name: str, row: dict[str, Any], budget_id: str) -> str:
    return (f"{name} ranked {row['rank']} of 15 for {budget_id} with expected excess return {row['expected_excess'] * 100:+.1f}% "
            f"and P(beat Nifty 500) {row['p_beat'] * 100:.0f}%; the top reason is: {row['reasons'][0] if row['reasons'] else 'n/a'}")


def _event_takeaway(name: str, curve: list[dict[str, Any]], budget_id: str) -> str | None:
    c = next((x for x in curve if x["window"] == "[0,+30]" and x["car"] is not None), None)
    if c is None:
        return None
    avg = f", against an average of {c['mean_car_all_budgets'] * 100:+.1f}% over {c['n_budgets']} budgets" if c["mean_car_all_budgets"] is not None else ""
    return f"{name} earned a {c['car'] * 100:+.1f}% abnormal return over the 30 days after the {budget_id} budget{avg}."


def _stock_rows(store: Store, budget_id: str) -> list[dict[str, Any]]:
    d = store.table("predictions_detail")
    d = d[(d["budget_id"] == budget_id) & (d["level"] == "stock") & (d["model"] == PRIMARY_STOCK_MODEL)]
    feats = store.table("features_stock_year_wide")
    feats = feats[feats["budget_id"] == budget_id].set_index("symbol")
    vol = feats["volatility_90d"]
    low, high = vol.quantile(1 / 3), vol.quantile(2 / 3)
    rows = []
    for r in d.sort_values("rank").to_dict("records"):
        f = feats.loc[r["entity"]] if r["entity"] in feats.index else None
        risk = None if f is None else ("low" if f["volatility_90d"] <= low else "high" if f["volatility_90d"] > high else "medium")
        reasons = json.loads(r["top_reasons"]) if isinstance(r.get("top_reasons"), str) else []
        rows.append({"symbol": r["entity"], "sector_id": r["sector_id"], "rank": int(r["rank"]), "expected_excess": r["expected_excess"], "p10": r["p10"], "p90": r["p90"],
                     "p_beat": r["p_beat"], "reasons": reasons, "realised_excess": r["actual"], "liquidity_cr": None if f is None else f["avg_traded_value_60d_cr"],
                     "volatility_90d": None if f is None else f["volatility_90d"], "beta_250d": None if f is None else f["beta_250d"], "risk": risk,
                     "order_win_flag": None, "source_ref": f"predictions_detail:{int(r['_row'])}",
                     "features_ref": None if f is None else f"features_stock_year_wide:{int(f['_row'])}"})
    return rows


def _stock_takeaway(rows: list[dict[str, Any]], budget_id: str) -> str | None:
    if not rows:
        return None
    top = rows[0]
    return (f"Highest-ranked stock for {budget_id} in this view: {top['symbol']} at {top['expected_excess'] * 100:+.1f}% expected excess return; "
            "stock forecasts are weaker than sector forecasts (see reports/models.md) and the list has survivorship bias.")


def _backtest(store: Store, root: Path) -> Any:
    lab = store.table("backtest_lab_summary")
    equity = {}
    for level in ("sector", "stock"):
        eq = pd.read_csv(root / "reports" / f"backtest_lab_equity_{level}.csv")
        eq["date"] = pd.to_datetime(eq["date"])
        weekly = eq.set_index("date").resample("W").last().reset_index()
        weekly["date"] = weekly["date"].dt.strftime("%Y-%m-%d")
        equity[level] = {"columns": [c for c in weekly.columns if c != "date"], "rows": records(weekly)}
    ic = store.table("ic_bootstrap")
    abl = store.table("ablation_summary")
    contrasts = pd.read_csv(root / "reports" / "ablation_contrasts.csv")
    per_year = store.table("models_per_year")
    holdout: dict[str, Any] = {"status": "not_run", "note": "The one-time hold-out evaluation (Phase 9) has not been run; FY2024-25 and FY2025-26 are locked."}
    result = root / "reports" / "holdout_result.json"
    if result.exists():
        holdout = {"status": "evaluated", "note": "One-time hold-out result; see reports/holdout.md.", "result": json.loads(result.read_text(encoding="utf-8"))}
    main = contrasts[(contrasts["contrast"] == "price_plus_budget minus price_only")]
    answer = ("; ".join(f"{r['model']}: IC change from adding budget data {r['ic_difference']:+.3f} (95% CI {r['ic_ci_lo']:+.3f} to {r['ic_ci_hi']:+.3f})" for r in main.to_dict("records")))
    return clean({
        "summary": _with_refs(lab, "backtest_lab_summary"), "equity": equity, "ic_by_year": _with_refs(per_year[["model", "budget_id", "ic", "_row"]], "models_per_year"),
        "ic_bootstrap": _with_refs(ic, "ic_bootstrap"), "ablation": _with_refs(abl, "ablation_summary"), "evidence_answer": answer,
        "takeaway": _backtest_takeaway(lab),
        "holdout": holdout, "ledger": {"entries": [], "note": "Sealed-prediction ledger not built yet (Phase 12)."}, "disclaimer": DISCLAIMER,
        "source_refs": {"summary": "backtest_lab_summary", "ic": "ic_bootstrap", "ablation": "ablation_summary"}})


def _backtest_takeaway(lab: pd.DataFrame) -> str:
    sharpe: dict[str, float] = {str(r["strategy"]): float(r["sharpe"]) for r in lab[lab["level"] == "sector"].to_dict("records")}
    models = [m for m in ("lgbm_ranker", "bayes_hier", "tier1_blend", "tier1_stack") if m in sharpe]
    best = max(models, key=lambda m: sharpe[m])
    beaten = [m for m in models if sharpe[m] > sharpe["equal_weight"]]
    margin = max((sharpe[m] - sharpe["equal_weight"] for m in beaten), default=0.0)
    verdict = ((f"{', '.join(beaten)} beat holding all 14 sectors equally on Sharpe by {margin:.2f}" + (" (within noise for 12 test years)" if margin < 0.1 else ""))
               if beaten else "none of the Tier-1 models beat holding all 14 sectors equally on Sharpe")
    return (f"Following the Tier-1 models since FY2012-13: best Sharpe {sharpe[best]:.2f} ({best}) against {sharpe['equal_weight']:.2f} for equal weight and "
            f"{sharpe['NIFTY500']:.2f} for the Nifty 500; {verdict}. Every portfolio beats the Nifty 500 partly because the baskets are survivorship-biased.")


def _with_refs(frame: pd.DataFrame, dataset: str) -> list[dict[str, Any]]:
    out = records(frame)
    for r in out:
        r["source_ref"] = f"{dataset}:{r.pop('_row')}"
    return out


def _credibility(store: Store) -> Any:
    panel = store.table("sector_budget_panel")
    latest = str(panel["budget_year"].max())
    # last budget whose credibility uses actuals (the panel holds all unlocked and later years; show the latest year with a value)
    sectors = []
    for sector_id, g in panel[panel["credibility_pct"].notna()].sort_values("budget_year").groupby("sector_id"):
        r = g.iloc[-1]
        sectors.append({"sector_id": sector_id, "sector_name": r["sector_name"], "budget_year": r["budget_year"], "credibility_pct": r["credibility_pct"],
                        "years_used": r["credibility_years_used"], "source_ref": f"sector_budget_panel:{int(r['_row'])}"})
    m = store.table("budget_ministries")
    m = m[m["line_type"] == "ministry"]
    league = []
    for name, g in m.groupby("canonical_name"):
        be = g[g["stage"] == "BE"].groupby("fiscal_year").first()
        act = g[g["stage"] == "Actual"].groupby("fiscal_year").first()
        years = sorted(set(be.index) & set(act.index))
        gaps = [(float(act.loc[y, "amount_cr"]) / float(be.loc[y, "amount_cr"]) - 1) * 100 for y in years if be.loc[y, "amount_cr"] and pd.notna(be.loc[y, "amount_cr"]) and pd.notna(act.loc[y, "amount_cr"])]
        if gaps:
            league.append({"ministry": name, "years": [y for y in years][:len(gaps)], "mean_gap_pct": sum(gaps) / len(gaps), "n_years": len(gaps),
                           "source_ref": f"budget_ministries:{int(act.loc[years[-1], '_row'])}"})
    league.sort(key=lambda r: float(str(r["mean_gap_pct"])))
    worst: Any = league[0] if league else None
    return clean({"latest_panel_year": latest, "sectors": sorted(sectors, key=lambda r: float(str(r["credibility_pct"] or 0))), "ministries": league,
                  "cga_monthly": {"available": False, "note": "The CGA monthly execution parser (D6) is not built."},
                  "takeaway": (f"{worst['ministry']} spent {abs(worst['mean_gap_pct']):.1f}% " + ("less" if worst["mean_gap_pct"] < 0 else "more") +
                               f" than budgeted on average over {worst['n_years']} year(s): the largest gap in the table.") if worst else None,
                  "definition": "Gap = Actual / Budget Estimate - 1 for the same fiscal year, from two PRS editions (BE from the budget year's own table, Actual from the edition two years later).",
                  "disclaimer": DISCLAIMER})


app = create_app()
