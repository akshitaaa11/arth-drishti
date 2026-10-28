"""Deterministic planner, writer and chart builder (README Phase 11).

Used (a) when no model is reachable, (b) in tests, and (c) for the charts in every mode: a chart is always built here, in code, from tool results,
so its numbers are traceable by construction. The writer only restates facts that tools returned and tags each sentence with its citation id.
"""

from __future__ import annotations

import re
from typing import Any

from bsp.copilot.tools import Tools, _norm, fiscal_year

_STOP = set("""what was the is are of in for to a an and how much did does do show me tell about budget estimate estimates revised actual allocation allocated allocations ministry
ministries scheme schemes fiscal year years rs crore spending spent actual revised in from by since between compare vs versus total please give amount number expected""".split())
_WHY = re.compile(r"\b(why|reason|reasons|explain|driv\w+|because)\b", re.I)
_FORECAST = re.compile(r"\b(forecast|expect\w*|predict\w*|beat|outperform\w*|rank\w*|excess return|probability|range)\b", re.I)
_STOCKS = re.compile(r"\b(stocks?|shares?|companies|top)\b", re.I)
_WHATIF = re.compile(r"\b(what[- ]?if|suppose|scenario|simulat\w*|if (the )?(government|allocation|budget))\b", re.I)
_EVENT = re.compile(r"\b(event|react\w*|abnormal|budget[- ]day|car\b|reaction)\b", re.I)
_LIVE = re.compile(r"\b(live|today|right now|current price|quote|latest price)\b", re.I)
_DOCS = re.compile(r"\b(how (was|were|is|are|do|does)|method\w*|leakage|look-?ahead|baseline|conformal|credib\w*|hold-?out|walk-?forward|data gap|survivorship|limitation)\b", re.I)
_CHANGE = re.compile(r"([A-Za-z][A-Za-z ]{1,25}?)\s+(?:allocation\s+)?(?:by\s+|to\s+)?(?:cut|reduc\w+|raise\w*|increase\w*|decrease\w*|up|down)?\s*(?:by\s+)?([+-]?\d+(?:\.\d+)?)\s*%", re.I)


def _content_words(question: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-&]+", question) if w.lower() not in _STOP]
    return " ".join(words)


def _years(question: str) -> list[str]:
    seen: list[str] = []
    for m in re.finditer(r"((?:19|20)\d{2})(?:\s?[-/–]\s?\d{2,4})?", question):
        fy = fiscal_year(m.group(0))
        if fy and fy not in seen:
            seen.append(fy)
    return seen


def _stage(question: str) -> str | None:
    q = question.lower()
    if "revised" in q or re.search(r"\bre\b", q):
        return "RE"
    if "actual" in q:
        return "Actual"
    if "budget estimate" in q or re.search(r"\bbe\b", q):
        return "BE"
    return None


def _budget_id(question: str) -> str | None:
    ys = _years(question)
    return f"FY{ys[0]}" if ys else None


def _known_item(question: str, tools: Tools) -> str | None:
    """The longest budget line name that appears verbatim in the question."""
    q = f" {_norm(question)} "
    best = ""
    for ds in ("budget_ministries", "budget_schemes", "budget_fiscal"):
        for name in tools.store.table(ds)["canonical_name"].dropna().unique():
            n = _norm(str(name))
            if len(n) > len(best) and f" {n} " in q:
                best = n
    return best or None


def plan(question: str, tools: Tools) -> list[tuple[str, dict[str, Any]]]:
    q = question.strip()
    sid = tools.sector_id(q)
    symbol = tools.stock_symbol(q)
    budget_id = _budget_id(q)
    steps: list[tuple[str, dict[str, Any]]] = []
    if _LIVE.search(q) and (sid or symbol or "quote" in q.lower() or "price" in q.lower()):
        return [("get_live_quotes", {"sector": sid})]
    if _WHATIF.search(q):
        changes: dict[str, float] = {}
        for m in _CHANGE.finditer(q):
            name = m.group(1).strip()
            target = tools.sector_id(name)
            if target:
                sign = -1.0 if re.search(r"cut|reduc|decreas|down|fall|lower", m.group(0), re.I) else 1.0
                val = float(m.group(2))
                changes[target] = val if val < 0 else sign * val
        if changes:
            return [("run_what_if", {"changes": changes})]
    if _EVENT.search(q) and (sid or symbol):
        return [("get_event_study", {"target": symbol or sid, "budget_id": budget_id})]
    if _WHY.search(q) and (sid or symbol):
        steps.append(("explain_prediction", {"target": symbol or sid, "budget_id": budget_id}))
        if sid and not symbol:
            steps.append(("get_sector_forecast", {"sector": sid, "budget_id": budget_id}))
        return steps
    if _STOCKS.search(q) and re.search(r"\b(stock|share|compan)", q, re.I):
        return [("get_stock_ranking", {"sector": sid, "budget_id": budget_id, "top": 5})]
    if _FORECAST.search(q) and sid:
        return [("get_sector_forecast", {"sector": sid, "budget_id": budget_id})]
    if _DOCS.search(q) and not _years(q):
        return [("search_documents", {"query": q})]
    item = _known_item(q, tools) or _content_words(q)
    if item:
        steps.append(("query_budget", {"item": item, "years": _years(q) or None, "stage": _stage(q)}))
    steps.append(("search_documents", {"query": q, "year": next(iter(_years(q)), None)}))
    return steps[:2]


# ---------------------------------------------------------------------------------------------- writer
def _cr(v: float) -> str:
    return f"Rs {v:,.0f} crore" if abs(v) >= 100 else f"Rs {v:,.2f} crore"


def _pct(frac: float) -> str:
    return f"{frac * 100:.1f}%"


def _write_one(res: dict[str, Any]) -> list[str]:
    tool, facts = res["tool"], res.get("facts") or []
    out: list[str] = []
    c = lambda f: f"[{f['cite_id']}]"  # noqa: E731
    if tool == "query_budget":
        for f in facts[:12]:
            out.append(f"{f['line_item']} ({f['line_type']}), {f['stage']} {f['fiscal_year']}: {_cr(f['amount'])} {c(f)}.")
    elif tool == "get_sector_forecast":
        for f in facts:
            ctrl = " This is a control sector with no direct budget link." if f.get("is_control_sector") else ""
            out.append(f"For {f['sector']} at {f['budget_id']} the model expected an excess return over the Nifty 500 of {_pct(f['expected_excess_return'])} "
                       f"(80% range {_pct(f['range_80pct_low'])} to {_pct(f['range_80pct_high'])}), a {_pct(f['probability_beat_nifty500'])} chance of beating it, "
                       f"ranked {f['rank_of_15']} of 15 {c(f)}.{ctrl}")
    elif tool == "get_stock_ranking":
        for f in facts:
            out.append(f"{f['symbol']} ({f['sector']}), overall rank {f['rank_overall']}: expected excess return {_pct(f['expected_excess_return'])}, "
                       f"80% range {_pct(f['range_80pct_low'])} to {_pct(f['range_80pct_high'])}, risk bucket {f['risk_bucket']} {c(f)}.")
    elif tool == "explain_prediction":
        for f in facts:
            reasons = f.get("reasons") or []
            text = " ".join(str(r) for r in reasons[:3])
            out.append(f"Main reasons for {f.get('sector') or f.get('symbol')} at {f['budget_id']}: {text} {c(f)}")
            for s in (f.get("largest_contributions_pp") or [])[:3]:
                out.append(f"Model driver {s['feature']}: {s['effect_percentage_points']:+.2f} percentage points {c(f)}.")
    elif tool == "run_what_if":
        for f in facts:
            out.append(f"{f['sector']}: allocation change {f['allocation_change_percent']:+.1f}%, rank {f['rank_before']} to {f['rank_after']}, "
                       f"expected return change {f['expected_return_change_percentage_points']:+.2f} percentage points {c(f)}.")
        if res.get("note"):
            out.append(str(res["note"]))
    elif tool == "get_event_study":
        for f in facts:
            if "mean_car" in f:
                out.append(f"{f['entity']} window {f['window']}: average cumulative abnormal return {_pct(f['mean_car'])} over {f['n_budgets']} budgets {c(f)}.")
            else:
                out.append(f"{f['entity']} at {f['budget_id']}, window {f['window']}: cumulative abnormal return {_pct(f['cumulative_abnormal_return'])} (t-statistic {f['t_stat']:.2f}) {c(f)}.")
    elif tool == "search_documents":
        for f in facts[:3]:
            body = re.sub(r"<[^>]+>", "", f["passage"]).strip()
            out.append(f"{body[:420]} {c(f)}")
    return out


def write(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for res in results:
        if res.get("ok"):
            lines.extend(_write_one(res))
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- charts
def chart_for(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """At most one chart or table, built only from tool facts."""
    for res in results:
        facts = res.get("facts") or []
        if not res.get("ok") or not facts:
            continue
        tool = res["tool"]
        if tool == "query_budget":
            stages = sorted({f["stage"] for f in facts})
            years = sorted({f["fiscal_year"] for f in facts})
            items = sorted({f["line_item"] for f in facts})
            if len(years) >= 2 and len(items) == 1:
                lookup = {(f["fiscal_year"], f["stage"]): f["amount"] for f in facts}
                return {"type": "line", "title": f"{items[0]} (Rs crore)", "x": years, "series": [{"name": s, "values": [lookup.get((y, s)) for y in years]} for s in stages]}
            if len(items) >= 2:
                return {"type": "table", "title": "Budget figures (Rs crore)", "columns": ["Item", "Year", "Stage", "Rs crore"],
                        "rows": [[f["line_item"], f["fiscal_year"], f["stage"], f["amount"]] for f in facts[:12]]}
        elif tool == "get_stock_ranking" and len(facts) >= 2:
            return {"type": "bar", "title": "Expected excess return vs Nifty 500 (%)", "x": [f["symbol"] for f in facts], "series": [{"name": "expected excess return %", "values": [round(f["expected_excess_return"] * 100, 2) for f in facts]}]}
        elif tool == "run_what_if":
            return {"type": "table", "title": "What-if: rank change", "columns": ["Sector", "Change %", "Rank before", "Rank after"],
                    "rows": [[f["sector"], f["allocation_change_percent"], f["rank_before"], f["rank_after"]] for f in facts]}
        elif tool == "get_event_study":
            f0 = facts[0]
            if "budgets" in f0:
                return {"type": "bar", "title": f"{f0['entity']} cumulative abnormal return {f0['window']} (%)", "x": [b["budget_id"] for b in f0["budgets"]],
                        "series": [{"name": "CAR %", "values": [round(b["car"] * 100, 2) for b in f0["budgets"]]}]}
    return None
