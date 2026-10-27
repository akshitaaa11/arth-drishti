"""Builds the hand-made speech PDFs used by tests/test_speech.py. The text is invented test text, NOT a real budget speech.

Run once (needs reportlab, a dev-only tool): ``python tests/fixtures/speeches/make_fixtures.py``. The PDFs are committed.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent

FIXTURES = {
    # fiscal year -> pages, each a list of lines (a sentence may continue on the next line or the next page)
    "2019-20": [
        ["FIXTURE SPEECH ONE (invented test text)",
         "The Ministry of Railways will receive a record outlay. We will launch a new scheme for station",
         "redevelopment. Dr. Rao said that Rs. 5.5 lakh crore is needed for the railway network."],
        ["2",
         "Highways and roads will see a big push in this year. Health and hospitals get nothing new!",
         "Farmers will be helped by PM-KISAN. The weather was fine."],
    ],
    "2020-21": [
        ["FIXTURE SPEECH TWO (invented test text)",
         "Defence production will grow. I propose to set up a new defence corridor. Banks are stable."],
    ],
    "2099-00": [["This file name is not a budget year, the parser must refuse it for the real folder."]],
}


def build() -> None:
    for name, pages in FIXTURES.items():
        pdf = canvas.Canvas(str(HERE / f"{name}.pdf"), pagesize=A4, invariant=1)
        for lines in pages:
            y = 800
            for line in lines:
                pdf.drawString(40, y, line)
                y -= 16
            pdf.showPage()
        pdf.save()
    pdf = canvas.Canvas(str(HERE / "scanned.pdf"), pagesize=A4, invariant=1)  # a page with no text layer at all
    pdf.rect(100, 100, 200, 200)
    pdf.showPage()
    pdf.save()


if __name__ == "__main__":
    build()
