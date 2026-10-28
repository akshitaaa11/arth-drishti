"""Number checker (README Phase 11): every number in a reply must be traceable to a tool result, a cited document chunk or the question.

``numbers_in`` extracts the numbers of a text as written (Indian or Western digit grouping, decimals, percentages, a leading minus); fiscal-year
and calendar-year tokens and list markers are not counted. ``untraceable`` returns the numbers of an answer that no evidence number reproduces
at the precision written. Evidence numbers match after these transforms: as is, times 100 (a fraction written as a percentage), divided by
1e5 (Rs crore written as Rs lakh crore) and divided by 1e2 / 1e3 / 1e7 (crore as Rs thousand/hundred crore or Rs trillion... kept narrow on purpose).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_YEAR_RANGE = re.compile(r"\b(?:FY)?\s?(?:19|20)\d{2}\s?[-/–]\s?(?:19|20)?\d{2}\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_LIST_MARKER = re.compile(r"(?m)^\s*(?:\d{1,2}[.)]|[-*•])\s+")
_NUMBER = re.compile(r"(?<![\w.])[-−]?\d[\d,]*(?:\.\d+)?(?![\w])")
TRANSFORMS = (1.0, 100.0, 1e-5, 1e-2, 1e-3, 1e-7)


@dataclass(frozen=True)
class Num:
    value: float
    decimals: int
    text: str


def strip_years(text: str) -> str:
    return _YEAR.sub(" ", _YEAR_RANGE.sub(" ", text))


def numbers_in(text: str, drop_years: bool = True) -> list[Num]:
    cleaned = _LIST_MARKER.sub("", re.sub("[\u2010-\u2015]", "-", text).replace("\u2212", "-"))
    if drop_years:
        cleaned = strip_years(cleaned)
    out: list[Num] = []
    for m in _NUMBER.finditer(cleaned):
        raw = m.group(0).replace("−", "-")
        digits = raw.replace(",", "")
        try:
            value = float(digits)
        except ValueError:
            continue
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        out.append(Num(value, decimals, raw))
    return out


def evidence_numbers(obj: Any) -> list[float]:
    """Every number inside a JSON-like structure (numbers, and numbers written inside strings)."""
    found: list[float] = []

    def walk(x: Any) -> None:
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            found.append(float(x))
        elif isinstance(x, str):
            found.extend(n.value for n in numbers_in(x, drop_years=False))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(obj)
    return found


def _matches(n: Num, evidence: Iterable[float]) -> bool:
    for e in evidence:
        for t in TRANSFORMS:
            candidate = e * t
            if round(candidate, n.decimals) == round(n.value, n.decimals) or abs(abs(candidate) - abs(n.value)) <= 0.5 * 10 ** (-n.decimals) + 1e-9:
                return True
            if n.decimals == 0 and abs(n.value) >= 1000 and abs(candidate - n.value) <= 0.005 * abs(n.value):  # large totals rounded to the unit
                return True
    return False


def untraceable(text: str, evidence: list[float], question: str = "") -> list[str]:
    """Numbers written in ``text`` that no evidence number (or number in the question) reproduces."""
    allowed = list(evidence) + [n.value for n in numbers_in(question, drop_years=False)]
    return [n.text for n in numbers_in(text) if not _matches(n, allowed)]
