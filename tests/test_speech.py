"""Phase 6: speech PDF parser, keyword sector tagger, talk-vs-money features. Fixtures are hand-made (tests/fixtures/speeches)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from bsp.common.config import get_project_root
from bsp.evaluation.config import load_config
from bsp.features.speech_features import SPEECH_FEATURES, add_speech_features
from bsp.nlp.speech_tagging import load_tagger, normalise, score_speeches
from bsp.parsers import speech as parser

ROOT = get_project_root()
FIX = Path(__file__).parent / "fixtures" / "speeches"


# ------------------------------------------------------------------ parser
def test_sentences_pages_abbreviations_and_page_numbers() -> None:
    frame = parser.parse_speech_pdf(FIX / "2019-20.pdf", "FY2019-20")
    assert frame["sentence_no"].tolist() == list(range(1, len(frame) + 1))
    texts = frame["text"].tolist()
    assert any(t.startswith("Dr. Rao said that Rs. 5.5 lakh crore") for t in texts)  # abbreviations and decimals do not split
    assert not any(t.strip() == "2" for t in texts)  # the page-number line is removed
    pages = dict(zip(frame["text"], frame["page"], strict=True))
    assert pages["We will launch a new scheme for station redevelopment."] == 1
    assert pages["Highways and roads will see a big push in this year."] == 2
    assert pages["Health and hospitals get nothing new!"] == 2  # "!" ends a sentence


def test_provenance_columns_and_hash() -> None:
    frame = parser.parse_speech_pdf(FIX / "2020-21.pdf", "FY2020-21")
    assert list(frame.columns) == parser.COLUMNS
    assert set(frame["budget_id"]) == {"FY2020-21"} and set(frame["source_file"]) == {"2020-21.pdf"}
    assert set(frame["source_sha256"]) == {hashlib.sha256((FIX / "2020-21.pdf").read_bytes()).hexdigest()}
    assert frame["extractor"].iloc[0].startswith("pdfplumber") and "not checked" in frame["source"].iloc[0]
    assert any("defence corridor" in t for t in frame["text"])


def test_a_pdf_without_text_is_refused_not_guessed() -> None:
    with pytest.raises(ValueError, match="no extractable text"):
        parser.parse_speech_pdf(FIX / "scanned.pdf", "FY2019-20")


def test_file_names_must_be_full_budget_years(tmp_path: Path) -> None:
    ids = parser.full_budget_ids(ROOT)
    assert len(ids) == 22 and ids["2009-10"] == "FY2009-10" and ids["2019-20"] == "FY2019-20"  # the full budget, not the interim one
    assert parser.budget_id_for_file(Path("2019-20.pdf"), ids) == "FY2019-20"
    with pytest.raises(ValueError, match="fiscal_year"):
        parser.budget_id_for_file(Path("2099-00.pdf"), ids)
    needed = pd.read_csv(ROOT / "reports" / "speech_pdfs_needed.csv")
    assert needed["file_name"].tolist() == [f"{y}.pdf" for y in ids] and needed["budget_id"].tolist() == list(ids.values())


def _root_with(tmp_path: Path, *names: str) -> Path:
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "budget_events.csv", tmp_path / "config")
    folder = tmp_path / "data" / "source_pdfs" / "speeches"
    folder.mkdir(parents=True)
    for name in names:
        shutil.copy(FIX / name, folder / name)
    return tmp_path


def test_parse_all_orders_by_budget_date_and_reports_bad_files(tmp_path: Path) -> None:
    root = _root_with(tmp_path, "2020-21.pdf", "2019-20.pdf", "2099-00.pdf", "scanned.pdf")
    frame, errors = parser.parse_all(root)
    assert frame["budget_id"].drop_duplicates().tolist() == ["FY2019-20", "FY2020-21"]
    assert len(errors) == 2 and any("2099-00.pdf" in e for e in errors) and any("scanned.pdf" in e for e in errors)
    again, _ = parser.parse_all(root)
    pd.testing.assert_frame_equal(frame, again)  # deterministic


def test_no_pdfs_gives_a_header_only_frame(tmp_path: Path) -> None:
    frame, errors = parser.parse_all(_root_with(tmp_path))
    assert list(frame.columns) == parser.COLUMNS and frame.empty and errors == []


# ------------------------------------------------------------------ tagger
def test_tagger_matches_whole_words_plurals_and_hyphens() -> None:
    tagger = load_tagger(ROOT)
    assert tagger.tag_sentence("Farmers will get PM-KISAN support.") == {"agriculture"}
    assert tagger.tag_sentence("The Ministry of Railways builds new railway lines.") == {"railways"}
    assert "healthcare" in tagger.tag_sentence("Hospitals and medical colleges") and "education" in tagger.tag_sentence("Hospitals and medical colleges")
    assert tagger.tag_sentence("Falling purchasing power hurts households.") == set()  # "power" alone is not a keyword
    assert tagger.tag_sentence("A broadband network for every village.") == {"telecom", "rural"}
    assert tagger.tag_sentence("The weather was fine.") == set()
    assert normalise("PM-KISAN & Co.") == "pm kisan co"


def test_announcement_cue_and_new_scheme_counts() -> None:
    tagger = load_tagger(ROOT)
    assert tagger.is_announcement("We will launch a new scheme.") and tagger.is_announcement("I propose to set up a fund.")
    assert not tagger.is_announcement("Highways and roads will see a big push.")
    sentences = pd.DataFrame({"budget_id": "FY2019-20", "text": [
        "We will launch a new scheme for station redevelopment of railways.",   # railways + cue
        "Railways carried more passengers this year.",                           # railways, no cue
        "I propose to set up a new body.",                                      # cue, no sector
        "Farmers get support."]})
    scores = score_speeches(sentences, tagger).set_index("sector_id")
    assert scores.loc["railways", "n_sentences"] == 4 and scores.loc["railways", "n_tagged"] == 2
    assert scores.loc["railways", "emphasis"] == 0.5 and scores.loc["railways", "new_scheme_n"] == 1
    assert scores.loc["agriculture", "new_scheme_n"] == 0 and scores.loc["defence", "emphasis"] == 0.0


def test_keyword_config_must_cover_exactly_the_sector_map(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "sector_map.json", tmp_path / "config")
    cfg = json.loads((ROOT / "config" / "sector_keywords.json").read_text())
    del cfg["sectors"]["roads"]
    (tmp_path / "config" / "sector_keywords.json").write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="missing .*roads"):
        load_tagger(tmp_path)


# ------------------------------------------------------------------ talk-vs-money features
def _records(budget: str, emphasis: list[float | None], surprise: list[float | None]) -> list[dict]:
    assert len(emphasis) == len(surprise)
    return [{"budget_id": budget, "sector_id": f"s{i}", "alloc_vs_prev_re_pct": value} for i, value in enumerate(surprise)]


def _scores(budget: str, emphasis: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"budget_id": budget, "sector_id": [f"s{i}" for i in range(len(emphasis))], "emphasis": emphasis,
                         "new_scheme_n": [1.0] * len(emphasis)})


def test_divergence_is_emphasis_rank_minus_surprise_rank_by_hand() -> None:
    records = _records("B1", [0.4, 0.3, 0.2, 0.1], [-1.0, 5.0, 2.0, 3.0])
    add_speech_features(records, _scores("B1", [0.4, 0.3, 0.2, 0.1]))
    # emphasis ranks 1,2,3,4; surprise ranks (highest = 1) 4,1,3,2; divergence = (e - s) / 4
    assert [r["speech_emphasis_rank"] for r in records] == [1.0, 2.0, 3.0, 4.0]
    assert [r["talk_vs_money_divergence"] for r in records] == [-0.75, 0.25, 0.0, 0.5]
    assert records[0]["speech_emphasis"] == 0.4 and set(SPEECH_FEATURES) <= set(records[0])


def test_missing_surprise_leaves_divergence_missing_and_ranks_use_only_common_sectors() -> None:
    records = _records("B1", [0.4, 0.3, 0.2], [None, 5.0, 2.0])
    add_speech_features(records, _scores("B1", [0.4, 0.3, 0.2]))
    assert records[0]["talk_vs_money_divergence"] is None and records[0]["speech_emphasis_rank"] == 1.0  # not 0, not filled
    # common sectors s1, s2: emphasis ranks 1,2; surprise ranks 1,2 -> divergence 0, 0
    assert records[1]["talk_vs_money_divergence"] == 0.0 and records[2]["talk_vs_money_divergence"] == 0.0


def test_a_budget_without_a_speech_has_missing_features_never_zero() -> None:
    records = _records("B1", [0.4, 0.3], [1.0, 2.0]) + _records("B2", [0.1, 0.2], [1.0, 2.0])
    add_speech_features(records, _scores("B1", [0.4, 0.3]))
    for record in records[2:]:
        assert all(record[f] is None for f in SPEECH_FEATURES)


def test_a_budgets_features_ignore_every_other_speech() -> None:
    base = _records("B1", [0.4, 0.3, 0.2], [3.0, 1.0, 2.0])
    only = [dict(r) for r in base]
    both = [dict(r) for r in base] + _records("B2", [0.9, 0.1, 0.5], [1.0, 2.0, 3.0])
    other = _scores("B2", [0.1, 0.9, 0.5])
    add_speech_features(only, _scores("B1", [0.4, 0.3, 0.2]))
    add_speech_features(both, pd.concat([_scores("B1", [0.4, 0.3, 0.2]), other]))
    assert only == both[:3]  # adding (or changing) another budget's speech does not move budget B1
    changed = [dict(r) for r in base] + _records("B2", [0.9, 0.1, 0.5], [1.0, 2.0, 3.0])
    add_speech_features(changed, pd.concat([_scores("B1", [0.4, 0.3, 0.2]), _scores("B2", [0.5, 0.5, 0.5])]))
    assert changed[:3] == only


# ------------------------------------------------------------------ feature store and the Phase 5 hook
def test_feature_store_has_speech_columns_and_no_value_for_budgets_without_a_speech() -> None:
    wide = pd.read_csv(ROOT / "data" / "csv" / "features_sector_year_wide.csv")
    assert set(SPEECH_FEATURES) <= set(wide.columns)
    scored = pd.read_csv(ROOT / "data" / "csv" / "speech_sector_scores.csv")
    without = wide[~wide["budget_id"].isin(set(scored["budget_id"]))]
    assert len(without) > 0 and without[SPEECH_FEATURES].isna().all().all()  # missing, never 0 or filled
    with_speech = wide[wide["budget_id"].isin(set(scored["budget_id"]))]
    if len(with_speech):
        assert with_speech["speech_emphasis"].between(0, 1).all()
        # the ranks of one budget are a permutation-with-ties of 1..n
        assert with_speech.groupby("budget_id")["speech_emphasis_rank"].min().eq(1.0).all()


def test_phase5_models_are_unchanged_by_default_and_speech_run_is_blocked_without_speeches(tmp_path: Path) -> None:
    from bsp.evaluation.data import SECTOR_FEATURES, load_sector_panel
    from bsp.models.run_models import run

    cfg = load_config()
    assert not set(SPEECH_FEATURES) & set(load_sector_panel(cfg).features)  # Phase 5 inputs untouched
    assert set(SPEECH_FEATURES) <= set(load_sector_panel(cfg, extra_features=tuple(SPEECH_FEATURES)).features)
    assert load_sector_panel(cfg).features == [c for c in SECTOR_FEATURES if c in load_sector_panel(cfg).frame.columns]
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "evaluation.json", tmp_path / "config")
    (tmp_path / "data" / "csv").mkdir(parents=True)
    pd.DataFrame(columns=["budget_id", "sector_id", "n_sentences", "n_tagged", "emphasis", "new_scheme_n"]).to_csv(
        tmp_path / "data" / "csv" / "speech_sector_scores.csv", index=False)
    with pytest.raises(SystemExit, match="BLOCKED"):
        run(load_config(tmp_path), use_mlflow=False, with_speech=True)
