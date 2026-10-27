"""Keyword sector tagging of budget-speech sentences, new-scheme detection and per-budget sector scores (README Phase 6, F6).

DEVIATION FROM THE README (zero-shot / FinBERT): the model host (huggingface.co) is blocked in the build environment, so
sentences are tagged by keywords instead, with no model download. There is NO sentiment score. The tagger is a plain
function of (sentence, keyword lists); a zero-shot or FinBERT tagger can replace ``tag_sentence`` later without changing the
output files or the feature code.

Keywords per sector = the sector's name and ``budget_lines`` from config/sector_map.json (whole phrases) plus the hand-written
lists in config/sector_keywords.json. A sentence is tagged with every sector it matches (so shares overlap and do not sum to 1).
A tagged sentence is a *new-scheme sentence* when it also matches one of the announcement cues in the same file
("new scheme", "launch", "set up", "establish", "propose", "announce", "introduce"). This is a heuristic for announcement-type
sentences; it cannot tell a genuinely new scheme from a continuing one, and it has not been checked against hand labels.

Output ``data/csv/speech_sector_scores.csv``: one row per budget with a speech and per sector: ``n_sentences`` (in the speech),
``n_tagged``, ``emphasis`` (= n_tagged / n_sentences), ``new_scheme_n``. A budget without a speech has no rows (its features
are missing, never zero).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from bsp.common.config import get_project_root

SCORE_COLUMNS = ["budget_id", "sector_id", "n_sentences", "n_tagged", "emphasis", "new_scheme_n"]


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


@dataclass(frozen=True)
class Tagger:
    patterns: dict[str, re.Pattern[str]]
    cues: tuple[re.Pattern[str], ...]

    def tag_sentence(self, sentence: str) -> set[str]:
        text = f" {normalise(sentence)} "
        return {sector for sector, pattern in self.patterns.items() if pattern.search(text)}

    def is_announcement(self, sentence: str) -> bool:
        return any(cue.search(sentence) for cue in self.cues)


def load_tagger(root: Path | None = None) -> Tagger:
    root = root or get_project_root()
    sector_map = json.loads((root / "config" / "sector_map.json").read_text(encoding="utf-8"))
    extra = json.loads((root / "config" / "sector_keywords.json").read_text(encoding="utf-8"))
    sector_ids = [s["sector_id"] for s in sector_map["sectors"]]
    missing = sorted(set(sector_ids) - set(extra["sectors"]))
    unknown = sorted(set(extra["sectors"]) - set(sector_ids))
    if missing or unknown:
        raise ValueError(f"config/sector_keywords.json must list exactly the sectors of sector_map.json "
                         f"(missing {missing}, unknown {unknown})")
    patterns: dict[str, re.Pattern[str]] = {}
    for sector in sector_map["sectors"]:
        terms = {normalise(t) for t in [sector["name"], *sector.get("budget_lines", []), *extra["sectors"][sector["sector_id"]]["keywords"]]}
        terms = {t for t in terms if len(t) >= 2}
        if not terms:
            raise ValueError(f"sector {sector['sector_id']} has no keywords")
        alternation = "|".join(re.escape(t) for t in sorted(terms, key=lambda t: (-len(t), t)))
        patterns[sector["sector_id"]] = re.compile(rf" (?:{alternation})(?:s|es)? ")
    cues = tuple(re.compile(c, re.IGNORECASE) for c in extra["new_scheme_cues"])
    return Tagger(patterns, cues)


def score_speeches(sentences: pd.DataFrame, tagger: Tagger) -> pd.DataFrame:
    """Per budget and sector: sentence counts, emphasis and new-scheme sentence count (see module docstring)."""
    rows = []
    for budget_id, speech in sentences.groupby("budget_id", sort=False):
        texts = speech["text"].astype(str).tolist()
        tags = [tagger.tag_sentence(t) for t in texts]
        announcements = [tagger.is_announcement(t) for t in texts]
        for sector in tagger.patterns:
            hit = [sector in t for t in tags]
            n_tagged = sum(hit)
            rows.append({"budget_id": budget_id, "sector_id": sector, "n_sentences": len(texts), "n_tagged": n_tagged,
                         "emphasis": n_tagged / len(texts) if texts else float("nan"),
                         "new_scheme_n": sum(h and a for h, a in zip(hit, announcements, strict=True))})
    return pd.DataFrame(rows, columns=SCORE_COLUMNS)


def build_and_save_speech_scores(root: Path | None = None) -> pd.DataFrame:
    """Read data/csv/speech_sentences.csv (header-only or absent = no speeches) and write speech_sector_scores.csv."""
    root = root or get_project_root()
    path = root / "data" / "csv" / "speech_sentences.csv"
    sentences = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["budget_id", "text"])
    scores = score_speeches(sentences, load_tagger(root))
    scores.to_csv(root / "data" / "csv" / "speech_sector_scores.csv", index=False, float_format="%.10g")
    return scores


if __name__ == "__main__":
    out = build_and_save_speech_scores()
    print(f"{out['budget_id'].nunique()} speech(es) scored -> data/csv/speech_sector_scores.csv")
