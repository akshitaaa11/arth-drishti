"""Guardrails of Budget Copilot (README Phase 11): advice refusal, prompt-injection refusal, off-topic redirect, document sanitising.

These are checked BEFORE any model sees the question, in plain code, so they hold even if a model misbehaves. Document text is data: passages are
wrapped and scrubbed of instruction-like phrases before they go into a prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DISCLAIMER = "Research tool, not investment advice."

_ADVICE = [
    r"\bshould i\b.*\b(buy|sell|invest|hold|short|put|park|switch|dump|add)\b", r"\b(buy|sell)\b.*\b(or)\b.*\b(hold|sell|buy)\b", r"\bis\b.*\b(a )?good (buy|investment|stock|pick)\b",
    r"\bwhat (should|do) i (buy|sell|do with my|invest)\b", r"\btell me what to (buy|sell|invest)\b", r"\brecommend\w*\b.*\b(stock|share|fund|sector|portfolio|investment)s?\b",
    r"\b(best|top|safest|right) (stock|share|sector|fund)s? (to|for me to)? ?(buy|invest|pick|own)\b", r"\bgive me (a )?(stock )?tips?\b", r"\binvest my\b", r"\bmy (savings|money|portfolio|retirement)\b",
    r"\bguarantee\w*\b", r"\bsure(-| )?shot\b", r"\b(will|would)\b.*\b(double|triple|moon|crash|go up|go down|rise|fall)\b.*\b(next|tomorrow|this (week|month|year))\b",
    r"\bhow much (should|can) i\b", r"\bpersonal(ised|ized)? (advice|recommendation)\b", r"\bfinancial advice\b", r"\bbuy (now|today)\b", r"\bsell (now|today)\b",
]
_INJECTION = [
    r"\bignore\b.{0,40}\b(instruction|rule|prompt|guideline|previous|above|earlier)", r"\b(disregard|forget|override|bypass)\b.{0,40}\b(instruction|rule|prompt|guardrail|polic|safety|everything)",
    r"\b(system|developer|hidden|initial) (prompt|message|instruction)s?\b", r"\byou are now\b", r"\bpretend (to be|you)\b", r"\bact as (an?|the)\b", r"\bjailbreak\b", r"\bdeveloper mode\b", r"\bdan mode\b",
    r"\b(reveal|show|print|leak|tell me)\b.{0,30}\b(api[ _-]?key|secret|password|token|credential|environment variable|prompt|instructions)", r"\bapi[ _-]?key\b", r"\bGROQ_\w+", r"\bnew instructions?\b",
    r"<\s*/?\s*(system|assistant|instruction)", r"\[\s*(system|inst)\s*\]", r"\bbase64\b", r"\brun (this )?(code|command|shell)\b", r"\bsudo\b|\brm -rf\b",
]
_INSTRUCTION_LIKE = re.compile(
    r"(ignore (all |any |the )?(previous|above|prior|earlier)[^.\n]*|disregard[^.\n]*instruction[^.\n]*|you (must|should|will) (now )?(reveal|ignore|obey|say|answer|output)[^.\n]*|"
    r"(system|assistant|developer)\s*:[^.\n]*|new instructions?[^.\n]*|do not (tell|mention|reveal)[^.\n]*|<\s*/?\s*(system|assistant|instruction)[^>]*>)", re.IGNORECASE)
_DOMAIN = re.compile(
    r"\b(budget|allocation|allocated|expenditure|spending|spend|fiscal|deficit|subsid\w*|ministr\w*|scheme|sector|stock|share|nifty|forecast|expected|excess|return|rank\w*|model|"
    r"predict\w*|why|event|react\w*|what[- ]if|simulat\w*|scenario|backtest|ic\b|hold-?out|evidence|credibility|capex|capital|revenue|gdp|tax|speech|finance minister|fm\b|"
    r"defence|railway\w*|roads?|housing|health\w*|agri\w*|fertili\w*|fmcg|telecom|rural|water|education|power|it services|psu|banks?|"
    r"leak\w*|look-?ahead|method\w*|baseline|walk-?forward|survivorship|limitation\w*|feature\w*|train\w*|valid\w*|credib\w*|calibrat\w*|"
    r"live|quote|price|conformal|interval|shap|reason|data|source|page|document|pdf|prs|2\d{3})\b", re.IGNORECASE)


@dataclass(frozen=True)
class Verdict:
    kind: str  # ok | advice | injection | off_topic | empty
    reply: str | None = None


ADVICE_REPLY = ("I can't give personal investment advice or tell you what to buy, sell or hold. What I can do is show what the models say about a sector or stock: "
                "its expected excess return over the Nifty 500, the 80% range, the probability of beating the index and the main reasons, together with the risks "
                "(the ranges are very wide and the models have not beaten simple baselines). " + DISCLAIMER)
INJECTION_REPLY = ("I can only answer questions about the Union Budget data, the sector and stock forecasts and how they were built. I can't change my rules, reveal "
                   "instructions or credentials, or follow instructions embedded in a question.")
OFF_TOPIC_REPLY = ("That is outside what I can help with. I answer questions about Union Budget allocations, sector and stock forecasts, event studies, what-if scenarios "
                   "and how the models and data work. For example: 'How much was the Defence ministry's budget estimate for 2019-20?'")


def classify(question: str) -> Verdict:
    q = (question or "").strip()
    if not q:
        return Verdict("empty", "Please type a question about the Union Budget, the sectors or the forecasts.")
    low = q.lower()
    if any(re.search(p, low) for p in _INJECTION):
        return Verdict("injection", INJECTION_REPLY)
    if any(re.search(p, low) for p in _ADVICE):
        return Verdict("advice", ADVICE_REPLY)
    if not _DOMAIN.search(q):
        return Verdict("off_topic", OFF_TOPIC_REPLY)
    return Verdict("ok")


def sanitize_document(text: str) -> tuple[str, bool]:
    """Remove instruction-like phrases from a document passage; returns (clean text, whether anything was removed)."""
    clean = _INSTRUCTION_LIKE.sub("[removed: instruction-like text]", text)
    return clean, clean != text


def wrap_document(text: str, label: str) -> str:
    clean, _ = sanitize_document(text)
    return f"<document source=\"{label}\">{clean}</document>"
