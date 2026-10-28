"""Document search for the Copilot (README Phase 11): passage + document + page.

DEVIATION FROM THE README (sentence-transformers): the model host (huggingface.co) is blocked in the build environment, so retrieval is TF-IDF
(word and bigram, cosine) over the same kinds of passages; a dense encoder can replace ``DocumentIndex.search`` without changing the tools.
Indexed passages (each carries a document name and a page or section, and a source reference when it comes from a CSV row):
  * budget table rows (ministries, schemes, fiscal totals, demands for grants): "Defence: Budget Estimate 2019-20 is Rs 431,011 crore" with the PRS page;
  * the project's own reports (reports/*.md), README.md and PRD.md, by paragraph, with the section heading as the "page";
  * budget-speech sentences (data/csv/speech_sentences.csv) once speeches exist (none today);
  * the text of PDFs placed in data/source_pdfs/ (the team's PRS analyses; not in the repository), one passage per paragraph, with the real page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from bsp.api.store import Store
from bsp.common.config import get_project_root

_YEAR = re.compile(r"(?:19|20)\d{2}(?:-\d{2})?")


@dataclass(frozen=True)
class Passage:
    pid: str
    text: str
    document: str
    page: str
    kind: str  # budget_row | report | speech | pdf
    source_ref: str | None = None


def _fmt_crore(v: float) -> str:
    return f"Rs {v:,.0f} crore"


class DocumentIndex:
    def __init__(self, root: Path | None = None, store: Store | None = None) -> None:
        self.root = root or get_project_root()
        self.store = store or Store(self.root)
        self.passages: list[Passage] = []
        self._build()
        self._fit()

    def _fit(self) -> None:
        texts = [p.text for p in self.passages]
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english", min_df=1)
        self.matrix = self.vectorizer.fit_transform(texts)

    # ------------------------------------------------------------------ building
    def _build(self) -> None:
        for dataset in ("budget_ministries", "budget_schemes", "budget_fiscal"):
            frame = self.store.table(dataset)
            for r in frame.to_dict("records"):
                if pd.isna(r["amount_cr"]):
                    continue
                stage = {"BE": "Budget Estimate", "RE": "Revised Estimate", "Actual": "Actual expenditure"}.get(str(r["stage"]), str(r["stage"]))
                unit = "" if r["unit"] == "rs_crore" else f" ({r['unit']})"
                amount = _fmt_crore(float(r["amount_cr"])) if r["unit"] == "rs_crore" else f"{float(r['amount_cr']):,.2f}{unit}"
                self.passages.append(Passage(f"{dataset}:{int(r['_row'])}", f"{r['canonical_name']} ({r['line_type']}): {stage} {r['fiscal_year']} is {amount}. Budget year {r['budget_year']}.",
                                             str(r["source_doc"]), str(r["source_page"]), "budget_row", f"{dataset}:{int(r['_row'])}"))
        for r in self.store.table("budget_demands").to_dict("records"):
            self.passages.append(Passage(f"budget_demands:{int(r['_row'])}", f"{r['ministry']} / {r['department']}: {r['stage']} {r['fiscal_year']} revenue {_fmt_crore(float(r['revenue_cr']))}, "
                                         f"capital {_fmt_crore(float(r['capital_cr']))}, total {_fmt_crore(float(r['total_cr']))}.", str(r["source_doc"]), str(r["source_page"]), "budget_row",
                                         f"budget_demands:{int(r['_row'])}"))
        docs = sorted((self.root / "reports").glob("*.md")) + [self.root / "README.md", self.root / "PRD.md"]
        for path in docs:
            if path.exists():
                self._add_markdown(path)
        speech = self.root / "data" / "csv" / "speech_sentences.csv"
        if speech.exists():
            frame = pd.read_csv(speech)
            for r in frame.to_dict("records"):
                self.passages.append(Passage(f"speech:{r['budget_id']}:{r['sentence_no']}", str(r["text"]), f"Budget speech {r['budget_id']}", f"p.{r['page']}", "speech"))
        pdfs = self.root / "data" / "source_pdfs"
        for pdf in sorted(pdfs.glob("*.pdf")) if pdfs.exists() else []:
            self._add_pdf(pdf)

    def _add_markdown(self, path: Path) -> None:
        heading = path.name
        for i, block in enumerate(re.split(r"\n\s*\n", path.read_text(encoding="utf-8"))):
            block = block.strip()
            if not block:
                continue
            m = re.match(r"#+\s+(.*)", block)
            if m:
                heading = m.group(1).strip()
            if len(block) < 40 or block.startswith("|---") or block.startswith("```"):
                continue
            self.passages.append(Passage(f"{path.name}:{i}", re.sub(r"\s+", " ", block)[:900], path.name, f"section: {heading}", "report"))

    def _add_pdf(self, pdf: Path) -> None:
        try:
            import pdfplumber

            with pdfplumber.open(pdf) as doc:
                for number, page in enumerate(doc.pages, start=1):
                    text = page.extract_text() or ""
                    for j, para in enumerate(re.split(r"\n\s*\n|(?<=\.)\n(?=[A-Z])", text)):
                        para = re.sub(r"\s+", " ", para).strip()
                        if len(para) > 60:
                            self.passages.append(Passage(f"{pdf.name}:{number}:{j}", para[:900], pdf.name, f"p.{number}", "pdf"))
        except Exception:  # an unreadable PDF is skipped, never guessed at
            return

    # ------------------------------------------------------------------ search
    def search(self, query: str, year: str | None = None, k: int = 5, kinds: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        scores = (self.matrix @ self.vectorizer.transform([query]).T).toarray().ravel()
        order = np.argsort(-scores, kind="stable")
        want = _YEAR.findall(year) if year else []
        out: list[dict[str, Any]] = []
        for i in order:
            if scores[i] <= 0 or len(out) >= k:
                break
            p = self.passages[i]
            if kinds and p.kind not in kinds:
                continue
            if want and not any(w in p.text or w in p.document for w in want):
                continue
            out.append({"id": p.pid, "text": p.text, "document": p.document, "page": p.page, "kind": p.kind, "source_ref": p.source_ref, "score": round(float(scores[i]), 4)})
        return out
