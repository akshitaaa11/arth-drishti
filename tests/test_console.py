"""The Streamlit analyst console runs without errors and shows the leakage and hold-out state."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_console_renders_every_tab_without_exceptions() -> None:
    at = AppTest.from_file(str(ROOT / "src" / "bsp" / "console" / "app.py"), default_timeout=120).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Freshness", "Data", "Leakage", "Models", "Hold-out"]
    assert any("point-in-time checks pass" in s.value for s in at.success)
    assert len(at.dataframe) >= 3 and "not investment advice" in " ".join(c.value for c in at.caption)
