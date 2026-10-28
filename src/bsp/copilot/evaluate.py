"""Runs the Copilot evaluation set and writes reports/copilot_eval.md (README Phase 11 exit criteria).

    python -m bsp.copilot.evaluate --mode offline          # deterministic planner/writer, no network
    python -m bsp.copilot.evaluate --mode live --pace 4    # real Groq calls (needs GROQ_API_KEY); paced for the free-tier rate limit
    python -m bsp.copilot.evaluate --mode live --disable-primary   # same, with the primary model switched off (backup-model drill)

Criteria: every number shown is traceable (the checker passes or the answer is the safe fallback); >=95% of known-answer questions cite the right PDF page;
every trick prompt is refused; the chatbot still works with the backup model.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from bsp.api.cache import MemoryCache
from bsp.api.store import Store
from bsp.common.config import get_project_root
from bsp.copilot.engine import Copilot
from bsp.copilot.groq_client import GroqClient


def _value_in(text: str, v: float) -> bool:
    forms = {f"{v:,.0f}", f"{v:.0f}", f"{v / 1e5:.2f}", f"{v / 1e5:,.1f}", f"{v / 1e5:.1f}"}
    return any(f in text for f in forms)


def run(root: Path, mode: str, pace: float, disable_primary: bool, limit: int | None = None) -> dict[str, Any]:
    client = GroqClient(api_key="" if mode == "offline" else None, retries=4)
    if disable_primary:
        client.disabled.add(client.model)
    copilot = Copilot(Store(root), client=client, cache=MemoryCache())
    known = json.loads((root / "tests" / "copilot_eval" / "known_answers.json").read_text())[:limit]
    tricks = json.loads((root / "tests" / "copilot_eval" / "trick_prompts.json").read_text())[:limit]
    rows: list[dict[str, Any]] = []
    for item in known:
        r = copilot.ask(item["question"])
        label = f"{item['source_doc']}, p.{item['source_page']}"
        rows.append({"id": item["id"], "kind": "known", "question": item["question"], "mode": r["mode"], "model": r["model"], "verified": r["verified"],
                     "value_correct": _value_in(r["answer"], item["expected_value"]), "citation_correct": any(c["label"] == label for c in r["citations"]),
                     "numbers_checked": r["numbers_checked"], "answer": r["answer"][:300]})
        time.sleep(pace if mode == "live" else 0)
    for item in tricks:
        r = copilot.ask(item["prompt"])
        rows.append({"id": item["id"], "kind": "trick", "question": item["prompt"], "expect": item["expect"], "mode": r["mode"], "refusal": r["refusal"],
                     "refused": r["mode"] == "refusal" and r["refusal"] == item["expect"], "answer": r["answer"][:160]})
    return {"mode": mode, "disable_primary": disable_primary, "models": {"primary": client.model, "backup": client.backup_model} if mode == "live" else None, "rows": rows,
            "calls": [c for c in client.calls]}


def summarise(res: dict[str, Any]) -> dict[str, Any]:
    known = [r for r in res["rows"] if r["kind"] == "known"]
    tricks = [r for r in res["rows"] if r["kind"] == "trick"]
    shown = [r for r in known if r["mode"] != "fallback"]
    served: dict[str, int] = {}
    for r in known:
        served[str(r["model"] or r["mode"])] = served.get(str(r["model"] or r["mode"]), 0) + 1
    return {"n_known": len(known), "n_tricks": len(tricks),
            "numbers_traceable": f"{sum(1 for r in known if r['verified'])}/{len(known)} answers verified ({sum(r['numbers_checked'] for r in known)} numbers checked)",
            "value_correct": sum(r["value_correct"] for r in known), "citation_correct": sum(r["citation_correct"] for r in known), "fallbacks": len(known) - len(shown),
            "tricks_refused": sum(r["refused"] for r in tricks), "served_by": served}


def report(res: dict[str, Any]) -> str:
    s = summarise(res)
    n, t = s["n_known"], s["n_tricks"]
    lines = [f"# Copilot evaluation ({res['mode']}{', primary model disabled' if res['disable_primary'] else ''})", "",
             f"- Known-answer questions: **{n}**; numbers traceable: **{s['numbers_traceable']}**.",
             f"- Correct value shown: **{s['value_correct']}/{n}** ({s['value_correct'] / max(n, 1):.0%}); correct PDF page cited: **{s['citation_correct']}/{n}** ({s['citation_correct'] / max(n, 1):.0%}); safe fallbacks: {s['fallbacks']}.",
             f"- Trick prompts refused: **{s['tricks_refused']}/{t}**.", f"- Answers served by: {s['served_by']}.", ""]
    if res.get("models"):
        lines.append(f"- Models: primary `{res['models']['primary']}`, backup `{res['models']['backup']}`; HTTP calls recorded: {len(res['calls'])} (statuses {sorted({c['status'] for c in res['calls']})}).")
        lines.append("")
    lines += ["| id | question | mode | value | page cited |", "|---|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['question']} | {r['mode']} | {'yes' if r['value_correct'] else 'NO'} | {'yes' if r['citation_correct'] else 'NO'} |" for r in res["rows"] if r["kind"] == "known"]
    lines += ["", "| id | prompt | expected | result |", "|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['question']} | {r['expect']} | {'refused' if r['refused'] else 'NOT REFUSED: ' + r['mode']} |" for r in res["rows"] if r["kind"] == "trick"]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["offline", "live"], default="offline")
    ap.add_argument("--pace", type=float, default=4.0)
    ap.add_argument("--disable-primary", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    root = get_project_root()
    res = run(root, a.mode, a.pace, a.disable_primary, a.limit)
    tag = a.mode + ("_backup" if a.disable_primary else "")
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / f"copilot_eval_{tag}.md").write_text(report(res), encoding="utf-8")
    (root / "reports" / f"copilot_eval_{tag}.json").write_text(json.dumps({"summary": summarise(res), "rows": res["rows"]}, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summarise(res), indent=1))


if __name__ == "__main__":
    main()
