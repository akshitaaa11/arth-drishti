"""The Copilot's read-only tools (README Phase 11; PRD section 8). None can change data or place an order.

Each tool returns ``{"ok", "tool", "note", "facts"}``; every fact has a ``cite`` (label, optional source_ref resolvable at /sources, optional dashboard screen).
The engine numbers the cites C1, C2, ... so an answer can reference them. Tool outputs are what the model may quote: numbers come from here, never from
the model's memory.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from bsp.api.store import PRIMARY_SECTOR_MODEL, PRIMARY_STOCK_MODEL, WINDOW_ORDER, Store, clean
from bsp.copilot.guardrails import wrap_document
from bsp.copilot.retrieval import DocumentIndex

ALIASES = {
    "it services": "it_control", "information technology": "it_control", "software": "it_control", "banks": "psu_banks", "banking": "psu_banks", "psu banks": "psu_banks",
    "pharma": "healthcare", "health": "healthcare", "hospitals": "healthcare", "farm": "agriculture", "farming": "agriculture", "agri": "agriculture", "fertiliser": "fertilisers", "fertilizer": "fertilisers",
    "fertilizers": "fertilisers", "food": "fmcg", "consumer": "fmcg", "railway": "railways", "rail": "railways", "road": "roads", "highways": "roads", "highway": "roads", "real estate": "housing",
    "telecommunications": "telecom", "digital": "telecom", "village": "rural", "jal shakti": "water", "renewables": "power", "energy": "power", "electricity": "power", "schools": "education",
}
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {"name": "search_documents", "description": "Search the project's documents (budget table rows with their PRS page, the project reports, speeches and PDFs when present). Returns passages with document and page.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "year": {"type": "string", "description": "optional fiscal year such as 2019-20"}, "k": {"type": "integer"}}, "required": ["query"]}},
    {"name": "query_budget", "description": "Budget figures in Rs crore (BE budget estimate, RE revised estimate, Actual) for a ministry, scheme or fiscal total, for given fiscal years.",
     "parameters": {"type": "object", "properties": {"item": {"type": "string", "description": "ministry, scheme or fiscal total name, e.g. Defence, PM-KISAN, Fiscal Deficit"},
                                                    "years": {"type": "array", "items": {"type": "string"}, "description": "fiscal years like 2019-20"}, "stage": {"type": "string", "enum": ["BE", "RE", "Actual"]}},
                    "required": ["item"]}},
    {"name": "get_sector_forecast", "description": "The Tier-1 model's out-of-sample forecast for a sector: expected excess return over the Nifty 500, 80% range, P(beat Nifty 500), rank of 15.",
     "parameters": {"type": "object", "properties": {"sector": {"type": "string"}, "budget_id": {"type": "string", "description": "e.g. FY2023-24; default the latest forecast budget"}}, "required": ["sector"]}},
    {"name": "get_stock_ranking", "description": "The Tier-2 model's ranked stocks (optionally within one sector) with expected excess return, range, liquidity and risk bucket.",
     "parameters": {"type": "object", "properties": {"sector": {"type": "string"}, "budget_id": {"type": "string"}, "top": {"type": "integer"}}, "required": []}},
    {"name": "explain_prediction", "description": "The three plain-English reasons and the largest SHAP contributions behind a sector's or stock's forecast.",
     "parameters": {"type": "object", "properties": {"target": {"type": "string", "description": "sector or stock symbol"}, "budget_id": {"type": "string"}}, "required": ["target"]}},
    {"name": "run_what_if", "description": "Change sector allocations by a percentage and re-rank the sectors with the Tier-1 model (an illustration, not a forecast).",
     "parameters": {"type": "object", "properties": {"changes": {"type": "object", "additionalProperties": {"type": "number"}, "description": "sector -> percent change, e.g. {\"railways\": -10}"},
                                                     "budget_id": {"type": "string"}}, "required": ["changes"]}},
    {"name": "get_event_study", "description": "Budget-day abnormal returns (market model) of a sector or stock: cumulative abnormal return in each window, this budget and the average over budgets.",
     "parameters": {"type": "object", "properties": {"target": {"type": "string"}, "budget_id": {"type": "string"}}, "required": ["target"]}},
    {"name": "get_live_quotes", "description": "Live prices and moves of a sector's stocks.", "parameters": {"type": "object", "properties": {"sector": {"type": "string"}}, "required": []}},
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9% ]+", " ", s.lower())).strip()


def fiscal_year(token: str) -> str | None:
    m = re.search(r"((?:19|20)\d{2})(?:\s?[-/–]\s?(\d{2,4}))?", str(token))
    if not m:
        return None
    start = int(m.group(1))
    return f"{start}-{str(start + 1)[-2:]}"


class Tools:
    def __init__(self, store: Store, index: DocumentIndex | None = None) -> None:
        self.store = store
        self._index = index
        self._simulator: Any = None
        self.sector_map = store.sector_map
        self.stock_sector = {s["symbol"]: x["sector_id"] for x in self.sector_map for s in x["stocks"]}

    @property
    def index(self) -> DocumentIndex:
        if self._index is None:
            self._index = DocumentIndex(self.store.root, self.store)
        return self._index

    # ------------------------------------------------------------------ entity resolution
    def sector_id(self, text: str) -> str | None:
        t = _norm(text)
        for s in self.sector_map:
            if t == s["sector_id"] or t == _norm(s["name"]):
                return str(s["sector_id"])
        for alias, sid in sorted(ALIASES.items(), key=lambda kv: -len(kv[0])):
            if re.search(rf"\b{re.escape(alias)}\b", t):
                return sid
        for s in self.sector_map:
            if s["sector_id"].replace("_control", "") in t.split() or any(_norm(w) == t for w in [s["name"].split(" ")[0]]):
                return str(s["sector_id"])
        for s in self.sector_map:
            if re.search(rf"\b{re.escape(s['sector_id'].replace('_', ' '))}\b", t) or any(w and w in t.split() for w in _norm(s["name"]).split()[:1]):
                return str(s["sector_id"])
        return None

    def stock_symbol(self, text: str) -> str | None:
        up = re.findall(r"[A-Za-z][A-Za-z0-9&-]{1,14}", text)
        for tok in up:
            if tok.upper() in self.stock_sector:
                return tok.upper()
        return None

    def _budget(self, budget_id: str | None) -> str:
        return budget_id or self.store.latest_forecast_budget()

    # ------------------------------------------------------------------ the tools
    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        fn = getattr(self, f"tool_{name}", None)
        if fn is None:
            return {"ok": False, "tool": name, "note": f"unknown tool {name!r}", "facts": []}
        try:
            result = fn(**{k: v for k, v in args.items() if v is not None})
        except TypeError as exc:
            return {"ok": False, "tool": name, "note": f"bad arguments: {exc}", "facts": []}
        result.setdefault("note", None)
        result["tool"] = name
        return clean(result)  # type: ignore[no-any-return]

    def tool_search_documents(self, query: str, year: str | None = None, k: int = 5) -> dict[str, Any]:
        hits = self.index.search(str(query), year=year, k=max(1, min(int(k), 8)))
        facts = [{"passage": wrap_document(h["text"], f"{h['document']} {h['page']}"), "document": h["document"], "page": h["page"],
                  "cite": {"label": f"{h['document']}, {h['page']}", "source_ref": h["source_ref"]}} for h in hits]
        return {"ok": bool(facts), "facts": facts, "note": None if facts else "No matching passage in the indexed documents (budget tables, project reports; no speeches or PDFs are loaded)."}

    def tool_query_budget(self, item: str, years: list[str] | str | None = None, stage: str | None = None) -> dict[str, Any]:
        wanted = sorted({y for y in (fiscal_year(t) for t in ([years] if isinstance(years, str) else (years or []))) if y})
        frames = []
        for dataset in ("budget_ministries", "budget_schemes", "budget_fiscal"):
            f = self.store.table(dataset).copy()
            f["dataset"] = dataset
            frames.append(f)
        frame = pd.concat(frames, ignore_index=True)
        frame = frame[frame["amount_cr"].notna()]
        names = frame.drop_duplicates("canonical_name")["canonical_name"].astype(str)
        q = _norm(item)
        exact = [n for n in names if _norm(n) == q]
        contained = [n for n in names if q and (q in _norm(n) or _norm(n) in q) and len(_norm(n)) >= 4]
        tokens = set(q.split()) - {"ministry", "of", "department", "the", "and", "budget", "allocation"}
        overlap = [n for n in names if tokens and tokens <= set(_norm(n).split())]
        matched = exact or contained or overlap
        if not matched:
            return {"ok": False, "facts": [], "note": f"No budget line matches {item!r}. Ministry, scheme and fiscal-total names are in the PRS tables for FY2017-18 onward."}
        matched = matched[:3]
        note = f"{item!r} matches {len(matched)} lines; showing all: {', '.join(matched)}." if len(matched) > 1 else None
        facts: list[dict[str, Any]] = []
        for name in matched:
            part = frame[frame["canonical_name"] == name]
            if wanted:
                part = part[part["fiscal_year"].astype(str).isin(wanted)]
            if stage:
                part = part[part["stage"] == stage]
            seen: dict[tuple[str, str], dict[str, Any]] = {}
            for rec in part.to_dict("records"):
                r: dict[str, Any] = {str(k): v for k, v in rec.items()}
                key = (str(r["fiscal_year"]), str(r["stage"]))
                start = int(str(r["fiscal_year"])[:4])
                preferred = {"BE": start, "RE": start + 1, "Actual": start + 2}.get(str(r["stage"]), start)
                rank = abs(int(str(r["budget_year"])[:4]) - preferred)
                if key not in seen or rank < seen[key]["_rank"]:
                    seen[key] = {**r, "_rank": rank}
            for (fy, st), r in sorted(seen.items()):
                unit = "Rs crore" if r["unit"] == "rs_crore" else str(r["unit"])
                facts.append({"line_item": name, "line_type": r["line_type"], "fiscal_year": fy, "stage": st, "amount": float(r["amount_cr"]), "unit": unit,
                              "document": r["source_doc"], "page": str(r["source_page"]),
                              "cite": {"label": f"{r['source_doc']}, p.{r['source_page']}", "source_ref": f"{r['dataset']}:{int(r['_row'])}"}})
        return {"ok": bool(facts), "facts": facts[:40], "note": note or (None if facts else "The line exists but has no figure for those years and stage.")}

    def _forecast_row(self, sector: str, budget_id: str, model: str = PRIMARY_SECTOR_MODEL) -> dict[str, Any] | None:
        frame = self.store.forecasts(budget_id, "sector", model)
        frame = frame[frame["entity"] == sector]
        return None if frame.empty else self.store.forecast_row(frame.iloc[0])

    def tool_get_sector_forecast(self, sector: str, budget_id: str | None = None) -> dict[str, Any]:
        sid = self.sector_id(sector)
        if sid is None:
            return {"ok": False, "facts": [], "note": f"Unknown sector {sector!r}. Sectors: {', '.join(s['sector_id'] for s in self.sector_map)}."}
        b = self._budget(budget_id)
        budget = self.store.budget(b)
        row = self._forecast_row(sid, b)
        if row is None:
            why = "locked hold-out" if budget and budget["status"] == "holdout_locked" else "no out-of-sample forecast exists for it"
            return {"ok": False, "facts": [], "note": f"No forecast for {sid} at {b}: {why}. Forecasts exist for FY2012-13 to FY2023-24."}
        facts = [{"sector": sid, "budget_id": b, "model": row["model"], "expected_excess_return": row["expected_excess"], "range_80pct_low": row["p10"], "range_80pct_high": row["p90"],
                  "probability_beat_nifty500": row["p_beat"], "rank_of_15": row["rank"], "is_control_sector": row["is_control"], "realised_excess_return_later": row["realised_excess"],
                  "note": "out-of-sample walk-forward forecast; expected return and range are fractions (0.10 = 10%)",
                  "cite": {"label": f"Sector forecast {sid}, {b} ({row['model']})", "source_ref": row["source_ref"], "screen": f"#/sector/{sid}"}}]
        return {"ok": True, "facts": facts}

    def tool_get_stock_ranking(self, sector: str | None = None, budget_id: str | None = None, top: int = 5) -> dict[str, Any]:
        b = self._budget(budget_id)
        sid = self.sector_id(sector) if sector else None
        if sector and sid is None:
            return {"ok": False, "facts": [], "note": f"Unknown sector {sector!r}."}
        from bsp.api.app import _stock_rows

        rows = _stock_rows(self.store, b)
        if sid:
            rows = [r for r in rows if r["sector_id"] == sid]
        if not rows:
            return {"ok": False, "facts": [], "note": f"No stock forecasts for {b}" + (f" in {sid}" if sid else "") + "."}
        facts = [{"symbol": r["symbol"], "sector": r["sector_id"], "budget_id": b, "model": PRIMARY_STOCK_MODEL, "rank_overall": r["rank"], "expected_excess_return": r["expected_excess"],
                  "range_80pct_low": r["p10"], "range_80pct_high": r["p90"], "probability_beat_nifty500": r["p_beat"], "liquidity_rs_crore": r["liquidity_cr"], "risk_bucket": r["risk"],
                  "cite": {"label": f"Stock forecast {r['symbol']}, {b}", "source_ref": r["source_ref"], "screen": "#/stocks"}} for r in rows[: max(1, min(int(top), 10))]]
        return {"ok": True, "facts": facts, "note": "stock forecasts are weaker than sector forecasts and the stock list has survivorship bias"}

    def tool_explain_prediction(self, target: str, budget_id: str | None = None) -> dict[str, Any]:
        b = self._budget(budget_id)
        symbol = self.stock_symbol(target)
        sid = self.sector_id(target)
        if sid and not (symbol and _norm(target) == symbol.lower()):
            row = self._forecast_row(sid, b)
            if row is None:
                return {"ok": False, "facts": [], "note": f"No forecast to explain for {sid} at {b}."}
            shap = [s for s in self.store.shap_for(b, sid) if s["shap"] is not None][:5]
            facts = [{"sector": sid, "budget_id": b, "reasons": row["reasons"],
                      "largest_contributions_pp": [{"feature": s["feature"], "value": s["feature_value"], "effect_percentage_points": round(s["shap"] * 100, 2)} for s in shap],
                      "cite": {"label": f"Reasons for {sid}, {b}", "source_ref": row["source_ref"], "screen": f"#/sector/{sid}"}}]
            return {"ok": True, "facts": facts}
        if symbol:
            from bsp.api.app import _stock_rows

            hit = next((r for r in _stock_rows(self.store, b) if r["symbol"] == symbol), None)
            if hit:
                return {"ok": True, "facts": [{"symbol": symbol, "budget_id": b, "reasons": hit["reasons"], "cite": {"label": f"Reasons for {symbol}, {b}", "source_ref": hit["source_ref"], "screen": "#/stocks"}}]}
        return {"ok": False, "facts": [], "note": f"Nothing to explain for {target!r} at {b}: not a modelled sector or stock."}

    def tool_run_what_if(self, changes: dict[str, float], budget_id: str | None = None) -> dict[str, Any]:
        from bsp.simulator.engine import SimulationError, Simulator

        mapped: dict[str, float] = {}
        for k, v in (changes or {}).items():
            sid = self.sector_id(str(k))
            if sid is None:
                return {"ok": False, "facts": [], "note": f"Unknown sector {k!r}."}
            mapped[sid] = float(v)
        b = budget_id or "FY2023-24"
        if self._simulator is None:
            self._simulator = Simulator(self.store.root)
        try:
            res = self._simulator.run(b, mapped, None)
        except SimulationError as exc:
            return {"ok": False, "facts": [], "note": str(exc)}
        movers = sorted((r for r in res["sectors"] if r["sector_id"] in mapped or r["rank_change"] != 0), key=lambda r: (r["sector_id"] not in mapped, -abs(r["rank_change"])))[:6]
        facts = [{"sector": r["sector_id"], "budget_id": b, "allocation_change_percent": r["change_pct"], "rank_before": r["rank_actual"], "rank_after": r["rank_scenario"],
                  "expected_return_change_percentage_points": round(r["expected_change"] * 100, 2), "surprise_before_percent": r["surprise_actual_pct"], "surprise_after_percent": r["surprise_scenario_pct"],
                  "cite": {"label": f"What-if {r['sector_id']}, {b}", "screen": "#/whatif"}} for r in movers]
        return {"ok": True, "facts": facts, "note": res["disclaimer"] + " " + res["takeaway"]}

    def tool_get_event_study(self, target: str, budget_id: str | None = None) -> dict[str, Any]:
        es = self.store.table("event_study")
        symbol = self.stock_symbol(target)
        sid = self.sector_id(target)
        if symbol and not (sid and _norm(target) == sid):
            entity, kind = symbol, "stock"
        elif sid:
            entity, kind = sid, "sector"
        else:
            return {"ok": False, "facts": [], "note": f"Unknown sector or stock {target!r}."}
        allowed = [x["budget_id"] for x in self.store.budgets() if x["status"] == "walk_forward_test"]
        rows = es[(es["entity_type"] == kind) & (es["entity"] == entity) & (es["budget_id"].isin(allowed))]
        if rows.empty:
            return {"ok": False, "facts": [], "note": f"No event-study rows for {entity}."}
        facts = []
        if budget_id:
            for w in WINDOW_ORDER:
                r = rows[(rows["budget_id"] == budget_id) & (rows["window"] == w)]
                if len(r):
                    facts.append({"entity": entity, "budget_id": budget_id, "window": w, "cumulative_abnormal_return": float(r["car"].iloc[0]), "t_stat": float(r["t_stat"].iloc[0]),
                                  "cite": {"label": f"Event study {entity}, {budget_id}, window {w}", "source_ref": f"event_study:{int(r['_row'].iloc[0])}", "screen": f"#/sector/{entity}" if kind == "sector" else None}})
        else:
            for w in ("[0,+5]", "[0,+30]"):
                sub = rows[rows["window"] == w].sort_values("budget_id")
                facts.append({"entity": entity, "window": w, "budgets": [{"budget_id": r["budget_id"], "car": float(r["car"])} for r in sub.to_dict("records")], "mean_car": float(sub["car"].mean()),
                              "n_budgets": int(len(sub)), "cite": {"label": f"Event study {entity}, window {w}, all budgets", "source_ref": f"event_study:{int(sub['_row'].iloc[0])}"}})
        return {"ok": bool(facts), "facts": facts, "note": "cumulative abnormal returns are fractions (0.05 = 5%) from a market model; windows count trading days from the budget day"}

    def tool_get_live_quotes(self, sector: str | None = None) -> dict[str, Any]:
        return {"ok": False, "facts": [], "note": "The live quote feed (D17) is not built yet (Phase 12), so there are no live prices or moves to report."}
