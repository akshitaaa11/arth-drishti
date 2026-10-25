"""Unit tests for the point-in-time Nifty 500 rebuild and universe filter (hand-made fixtures only)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from scripts.collect.nifty500_history import build_intervals, normalise_name, parse_release_text

from bsp.features.universe import Universe
from bsp.quality.leakage import LeakageError, validate_index_membership

FIX = Path(__file__).parent / "fixtures" / "nifty500"
NAME_MAP = {
    normalise_name("Alpha Corp Limited"): "ALPHA",
    normalise_name("Beta Industries Limited"): "BETA",
    normalise_name("Gamma Ltd"): "GAMMA",
    normalise_name("Delta Co"): "DELTA",
}


def _changes():
    return [
        parse_release_text((FIX / f"{d}.txt").read_text(), date.fromisoformat(d), source=f"{d}.txt", source_url="u")
        for d in ("2020-03-30", "2022-09-30")
    ]


def test_parser_reads_only_the_nifty500_section() -> None:
    change = parse_release_text((FIX / "2020-03-30.txt").read_text(), date(2020, 3, 30))
    assert change is not None
    assert change.included == ["Alpha Corp Limited"]
    assert change.excluded == ["Beta Industries Limited", "Gamma Ltd"]


def test_parser_returns_none_without_nifty500_section() -> None:
    assert parse_release_text("Nifty 50\nCompanies Included\n1. X Ltd\n", date(2020, 1, 1)) is None


def test_reverse_walk_builds_intervals_and_stops_at_coverage_start() -> None:
    # Today: ALPHA left in 2022, BETA returned in 2022; DELTA never changed. GAMMA left in 2020.
    intervals, unmapped = build_intervals({"BETA", "DELTA"}, _changes(), NAME_MAP, "cur", "t")
    assert unmapped == []
    got = {(r.symbol, str(r.effective_from), None if pd.isna(r.effective_to) else str(r.effective_to))
           for r in intervals.itertuples()}
    assert got == {
        ("BETA", "2022-09-30", None),            # re-included in 2022
        ("BETA", "2020-03-29", "2020-03-29"),    # member only up to the day before the 2020 exclusion
        ("ALPHA", "2020-03-30", "2022-09-29"),   # included 2020, excluded 2022
        ("GAMMA", "2020-03-29", "2020-03-29"),
        ("DELTA", "2020-03-29", None),            # member throughout known coverage
    }
    assert intervals["effective_from"].min() == date(2020, 3, 29)  # nothing earlier is filled
    assert {"symbol", "effective_from", "effective_to", "source", "source_url", "fetched_at"} <= set(intervals.columns)


def test_universe_members_respects_coverage() -> None:
    intervals, _ = build_intervals({"BETA", "DELTA"}, _changes(), NAME_MAP, "cur", "t")
    uni = Universe(intervals.assign(effective_from=intervals["effective_from"].astype(str),
                                    effective_to=intervals["effective_to"].astype(str)))
    assert uni.members("2019-01-01") is None          # before coverage: no information
    assert uni.members("2021-01-01") == {"ALPHA", "DELTA"}
    assert uni.members("2023-01-01") == {"BETA", "DELTA"}
    assert Universe(None).members("2021-01-01") is None


def test_leakage_catches_out_of_universe_stock() -> None:
    uni = Universe(pd.DataFrame([{"symbol": "ALPHA", "effective_from": "2020-03-29", "effective_to": None}]))
    events = pd.DataFrame([{"budget_id": "FY2021-22", "fiscal_year": "2021-22", "presented_on": "2021-02-01"}])
    ok = pd.DataFrame([{"symbol": "ALPHA", "budget_id": "FY2021-22"}])
    validate_index_membership(ok, uni, events)
    leaked = pd.DataFrame([{"symbol": "ZZZ", "budget_id": "FY2021-22"}])
    with pytest.raises(LeakageError) as exc:
        validate_index_membership(leaked, uni, events)
    assert "ZZZ appears in FY2021-22" in str(exc.value)
