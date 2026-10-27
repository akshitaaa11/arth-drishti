"""Budget speech PDFs -> ``data/csv/speech_sentences.csv`` (README Phase 6, D15).

Input: one PDF per full budget at ``data/source_pdfs/speeches/<fiscal_year>.pdf`` (for example ``2019-20.pdf`` is the
FY2019-20 *full* budget speech of 5 July 2019; interim-budget speeches are not read). Text comes from the PDF's own text layer
(pdfplumber). A scanned PDF with no text layer is reported and skipped: nothing is OCR-guessed and no text is ever invented.

Output columns: ``budget_id, sentence_no, page, text`` plus provenance ``source_file, source_sha256, extractor, source``.
``sentence_no`` counts the kept sentences of one speech from 1; ``page`` is the PDF page (1-based) where the sentence starts.

Cleaning rules (all deterministic): lines that are only a page number are removed; lines are joined with a space (a hyphen at a
line end is kept, so "long-" + "term" reads "long-term" but a hyphenated word split by the typesetter stays split); sentences end
at . ! ? followed by a capital letter, digit or opening quote, except after common abbreviations (Rs., No., Dr., Shri ...);
sentences shorter than 4 words (headings, page furniture) are dropped.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from bisect import bisect_right
from pathlib import Path

import pandas as pd

from bsp.common.config import get_project_root

SOURCE_NOTE = "budget speech PDF supplied by the team (data/source_pdfs/speeches/); not checked against indiabudget.gov.in"
COLUMNS = ["budget_id", "sentence_no", "page", "text", "source_file", "source_sha256", "extractor", "source"]
MIN_WORDS = 4
ABBREVIATIONS = ["Rs", "No", "Nos", "Dr", "Mr", "Mrs", "Ms", "Smt", "Shri", "Sri", "Prof", "Hon", "St", "vs", "etc", "viz",
                 "i.e", "e.g", "approx", "Sh", "Km", "Mt", "Lt", "Gen", "Col", "Capt", "Fig", "Vol", "Ltd", "Pvt", "Co", "Inc"]
_PAGE_NUMBER = re.compile(r"^\s*(?:page\s+)?\d{1,3}\s*$", re.IGNORECASE)
_PROTECT = re.compile(r"\b(" + "|".join(re.escape(a) for a in ABBREVIATIONS) + r")\.", re.IGNORECASE)
_BOUNDARY = re.compile(r"(?<=[.!?])[\"')”’]*\s+(?=[\"'(“‘]*[A-Z0-9])")
_DOT = "․"  # one-dot leader, stands in for a protected abbreviation period while splitting


def speech_dir(root: Path | None = None) -> Path:
    return (root or get_project_root()) / "data" / "source_pdfs" / "speeches"


def full_budget_ids(root: Path | None = None) -> dict[str, str]:
    """fiscal year -> budget_id of the FULL budget (config/budget_events.csv)."""
    events = pd.read_csv((root or get_project_root()) / "config" / "budget_events.csv")
    full = events[events["budget_type"] == "full"]
    return dict(zip(full["fiscal_year"].astype(str), full["budget_id"].astype(str), strict=True))


def budget_id_for_file(path: Path, ids: dict[str, str]) -> str:
    year = path.stem
    if year not in ids:
        raise ValueError(f"{path.name}: file name must be <fiscal_year>.pdf for a full budget, one of: {', '.join(sorted(ids))}")
    return ids[year]


def extract_pages(pdf_path: Path) -> list[str]:
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def clean_page(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    return " ".join(ln for ln in lines if ln and not _PAGE_NUMBER.match(ln))


def split_sentences(pages: list[str]) -> list[tuple[int, str]]:
    """(page, sentence) for every kept sentence, in reading order; ``page`` is where the sentence starts."""
    full, starts = "", []
    for number, raw in enumerate(pages, start=1):
        cleaned = clean_page(raw)
        if cleaned:
            starts.append((len(full), number))
            full += cleaned + " "
    if not full:
        return []
    protected = _PROTECT.sub(lambda m: m.group(1) + _DOT, full)
    offsets = [0] + [m.end() for m in _BOUNDARY.finditer(protected)] + [len(protected)]
    positions = [s for s, _ in starts]
    out: list[tuple[int, str]] = []
    for begin, end in zip(offsets, offsets[1:], strict=False):
        sentence = protected[begin:end].replace(_DOT, ".").strip()
        if len(sentence.split()) >= MIN_WORDS:
            out.append((starts[bisect_right(positions, begin) - 1][1] if begin >= positions[0] else starts[0][1], sentence))
    return out


def parse_speech_pdf(path: Path, budget_id: str) -> pd.DataFrame:
    import pdfplumber

    pages = extract_pages(path)
    sentences = split_sentences(pages)
    if not sentences:
        raise ValueError(f"{path.name}: no extractable text (scanned PDF?); nothing was guessed")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = [{"budget_id": budget_id, "sentence_no": i, "page": page, "text": text, "source_file": path.name,
             "source_sha256": digest, "extractor": f"pdfplumber {pdfplumber.__version__}", "source": SOURCE_NOTE}
            for i, (page, text) in enumerate(sentences, start=1)]
    return pd.DataFrame(rows, columns=COLUMNS)


def parse_all(root: Path | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Parse every PDF in the speech folder. Returns (all sentences ordered by budget date, error messages)."""
    root = root or get_project_root()
    ids = full_budget_ids(root)
    order = {b: i for i, b in enumerate(pd.read_csv(root / "config" / "budget_events.csv").sort_values("presented_on")["budget_id"])}
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    folder = speech_dir(root)
    for path in sorted(folder.glob("*.pdf")) if folder.exists() else []:
        try:
            frames.append(parse_speech_pdf(path, budget_id_for_file(path, ids)))
        except Exception as exc:  # report the file, keep the others
            errors.append(f"{path.name}: {exc}")
    if not frames:
        return pd.DataFrame(columns=COLUMNS), errors
    frame = pd.concat(frames, ignore_index=True)
    frame["_order"] = frame["budget_id"].map(order)
    return frame.sort_values(["_order", "sentence_no"]).drop(columns="_order").reset_index(drop=True), errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = args.root or get_project_root()
    frame, errors = parse_all(root)
    out = root / "data" / "csv" / "speech_sentences.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out, index=False)
    counts = frame.groupby("budget_id").size().to_dict() if len(frame) else {}
    print(f"{len(frame)} sentences from {len(counts)} speech(es) -> {out}")
    for budget_id, n in counts.items():
        print(f"  {budget_id}: {n} sentences")
    if not len(frame) and not errors:
        print(f"No PDFs found in {speech_dir(root)}; wrote a header-only CSV. Expected file names: reports/speech_pdfs_needed.csv")
    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
