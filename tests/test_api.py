"""Phase 10 API: endpoints, provenance, cache, simulator, hold-out safety and latency (README FR-12)."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from bsp.api.app import create_app
from bsp.api.cache import MemoryCache, RedisCache, make_cache

ROOT = Path(__file__).resolve().parents[1]
LOCKED = ["FY2024-25", "FY2025-26", "FY2026-27"]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(ROOT, MemoryCache()))


# ---------------------------------------------------------------- budgets and honesty about what is not there
def test_budgets_list_statuses_and_no_forecast_for_locked_budgets(client: TestClient) -> None:
    data = client.get("/budgets").json()
    budgets = {b["budget_id"]: b for b in data["budgets"]}
    assert len(budgets) == 26 and data["latest_forecast_budget"] == "FY2023-24" and "not investment advice" in data["disclaimer"]
    assert budgets["FY2023-24"]["status"] == "walk_forward_test" and budgets["FY2023-24"]["has_forecast"]
    assert budgets["FY2024-25"]["status"] == budgets["FY2025-26"]["status"] == "holdout_locked"
    assert budgets["FY2026-27"]["status"] == "live_sealed" and budgets["FY2019-20-I"]["status"] == "interim_not_modelled"
    assert not any(budgets[b]["has_forecast"] for b in LOCKED)
    for b in LOCKED:
        r = client.get(f"/budgets/{b}/forecast").json()
        assert r["sectors"] == [] and r["note"] and not r["out_of_sample"]
        assert client.get(f"/sectors/defence/forecast?budget_id={b}").status_code == 404


def test_budget_lines_have_sources_and_missing_years_say_so(client: TestClient) -> None:
    r = client.get("/budgets/FY2019-20/lines?kind=ministry").json()
    defence = next(i for i in r["items"] if i["line_item"] == "Defence")
    assert defence["be"]["amount_cr"] > 0 and defence["actual"]["source_ref"].startswith("budget_ministries:") and r["takeaway"]
    assert client.get("/budgets/FY2019-20/lines?kind=demand").json()["available"]
    old = client.get("/budgets/FY2007-08/lines").json()
    assert old["available"] is False and "not collected" in old["note"]
    assert client.get("/budgets/FY1999-00/lines").status_code == 404 and client.get("/budgets/FY2019-20/lines?kind=bogus").status_code == 422


def test_not_built_features_are_reported_as_not_built(client: TestClient) -> None:
    ledger = client.get("/ledger").json()
    assert ledger["entries"] == [] and "not built" in ledger["note"]
    assert client.get("/credibility").json()["cga_monthly"]["available"] is False
    stocks = client.get("/stocks?budget_id=FY2023-24").json()
    assert "not available" in stocks["order_win_flag"] and all(s["order_win_flag"] is None for s in stocks["stocks"])
    assert client.get("/backtest").json()["holdout"]["status"] == "not_run"


# ---------------------------------------------------------------- forecasts
def test_heatmap_has_15_ranked_sectors_with_intervals_reasons_and_sources(client: TestClient) -> None:
    r = client.get("/budgets/FY2023-24/forecast").json()
    rows = r["sectors"]
    assert sorted(x["rank"] for x in rows) == list(range(1, 16)) and sum(x["is_control"] for x in rows) == 1
    assert all(x["p10"] < x["expected_excess"] + 1e-9 or x["p10"] < x["p90"] for x in rows) and all(x["p10"] < x["p90"] for x in rows)
    assert all(len(x["reasons"]) == 3 and 0 <= x["p_beat"] <= 1 for x in rows)
    ref = rows[0]["source_ref"]
    assert client.get(f"/sources/{ref}").json()["row_values"]["entity"] == rows[0]["entity"]
    assert client.get("/budgets/FY2023-24/forecast?model=nope").status_code == 422


def test_sector_forecast_cards_shap_and_history(client: TestClient) -> None:
    r = client.get("/sectors/defence/forecast?budget_id=FY2023-24").json()
    assert r["forecast"]["rank"] >= 1 and set(r["cards"]) == {"surprise", "credibility"} and r["takeaway"]
    shap = r["shap"]
    assert len(shap) == 22 and {"feature", "feature_value", "shap", "base"} <= set(shap[0])
    assert abs(shap[0]["base"] + sum(s["shap"] for s in shap) - r["forecast"]["expected_excess"]) < 0.02  # additive up to Monte-Carlo noise
    assert len(r["history"]) == 12
    assert client.get("/sectors/nope/forecast").status_code == 404


def test_event_study_curve_and_fpi_strip(client: TestClient) -> None:
    r = client.get("/sectors/defence/event-study?budget_id=FY2021-22").json()
    assert [c["window"] for c in r["curve"]] == ["[-5,-1]", "0", "[0,+5]", "[0,+30]", "[0,+90]"] and r["takeaway"]
    assert all(c["car"] is not None and c["source_ref"].startswith("event_study:") for c in r["curve"])
    assert client.get("/sectors/defence/event-study?budget_id=FY2025-26").status_code == 404  # locked


def test_stock_watchlist_filters_and_detail(client: TestClient) -> None:
    all_rows = client.get("/stocks?budget_id=FY2023-24").json()["stocks"]
    assert len(all_rows) > 50 and {r["risk"] for r in all_rows} == {"low", "medium", "high"} and all(r["liquidity_cr"] >= 5 for r in all_rows)
    sector = client.get("/stocks?budget_id=FY2023-24&sector=defence").json()["stocks"]
    assert sector and {r["sector_id"] for r in sector} == {"defence"}
    high = client.get("/stocks?budget_id=FY2023-24&risk=high").json()["stocks"]
    assert high and {r["risk"] for r in high} == {"high"}
    detail = client.get(f"/stocks/{sector[0]['symbol'].lower()}?budget_id=FY2023-24").json()
    assert detail["stock"]["symbol"] == sector[0]["symbol"] and len(detail["stock"]["reasons"]) == 3 and detail["history"]
    assert client.get("/stocks/NOTASTOCK").status_code == 404


def test_backtest_and_credibility_payloads(client: TestClient) -> None:
    b = client.get("/backtest").json()
    strategies = {r["strategy"] for r in b["summary"] if r["level"] == "sector"}
    assert {"equal_weight", "ridge", "NIFTY500", "tier1_blend"} <= strategies
    assert len(b["equity"]["sector"]["rows"]) > 400 and "price_plus_budget" not in b["evidence_answer"] and "IC change" in b["evidence_answer"]
    c = client.get("/credibility").json()
    assert len(c["sectors"]) >= 10 and len(c["ministries"]) > 5 and c["ministries"][0]["mean_gap_pct"] <= c["ministries"][-1]["mean_gap_pct"]


# ---------------------------------------------------------------- provenance
def test_sources_return_the_row_and_its_provenance(client: TestClient) -> None:
    r = client.get("/sources/budget_ministries:3").json()
    assert r["dataset"] == "budget_ministries" and r["provenance"]["source_doc"].endswith(".pdf") and r["provenance"]["source_page"] and len(r["file_sha256"]) == 64
    assert client.get("/sources/nope:1").status_code == 404 and client.get("/sources/budget_ministries:99999999").status_code == 404
    assert client.get("/sources/budget_ministries:abc").status_code == 404


def test_source_pdf_is_served_only_when_the_file_is_in_the_repository(client: TestClient) -> None:
    row = client.get("/sources/budget_ministries:3").json()
    target = ROOT / "data" / "source_pdfs" / row["provenance"]["source_doc"]
    assert client.get("/sources/budget_ministries:3/pdf").status_code in (404, 200)
    created = not target.exists()
    if created:
        shutil.copy(ROOT / "tests" / "fixtures" / "speeches" / "2019-20.pdf", target)
    try:
        assert client.get("/sources/budget_ministries:3").json()["pdf_available"] is True
        pdf = client.get("/sources/budget_ministries:3/pdf")
        assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    finally:
        if created:
            target.unlink()


# ---------------------------------------------------------------- what-if engine
def test_simulator_reproduces_the_feature_formulas_and_is_a_no_op_without_changes(client: TestClient) -> None:
    base = client.post("/simulate", json={"budget_id": "FY2019-20"}).json()
    assert all(s["rank_actual"] == s["rank_scenario"] and s["expected_change"] == 0 for s in base["sectors"]) and "No allocation" in base["takeaway"]
    r = client.post("/simulate", json={"budget_id": "FY2019-20", "changes": {"defence": 50}}).json()
    d = next(s for s in r["sectors"] if s["sector_id"] == "defence")
    assert d["be_scenario_cr"] == pytest.approx(d["be_actual_cr"] * 1.5)
    panel = pd.read_csv(ROOT / "data" / "csv" / "features_sector_year_wide.csv")
    row = panel[(panel["sector_id"] == "defence") & (panel["budget_id"] == "FY2019-20")].iloc[0]
    assert d["surprise_actual_pct"] == pytest.approx(row["alloc_vs_prev_re_pct"], abs=0.01)  # the formula reproduces the stored feature
    assert d["surprise_scenario_pct"] == pytest.approx((row["be_current_cr"] * 1.5 / row["re_previous_cr"] - 1) * 100)
    assert len(d["reasons"]) == 3 and "not a forecast" in r["disclaimer"]
    others = [s for s in r["sectors"] if s["sector_id"] != "defence"]
    assert all(s["expected_change"] == 0 and s["change_pct"] == 0 for s in others)


def test_simulator_presets_and_validation(client: TestClient) -> None:
    presets = client.get("/simulate/presets").json()
    ids = [p["id"] for p in presets["presets"]]
    assert "actual" in ids and "flat_vs_re" in ids and "replay:FY2021-22" in ids and len(presets["sectors"]) == 15
    flat = client.post("/simulate", json={"budget_id": "FY2019-20", "preset": "flat_vs_re"}).json()
    surprises = [s["surprise_scenario_pct"] for s in flat["sectors"] if s["surprise_scenario_pct"] is not None]
    assert surprises and max(abs(x) for x in surprises) < 1e-6  # zero surprise everywhere
    replay = client.post("/simulate", json={"budget_id": "FY2019-20", "preset": "replay:FY2021-22"}).json()
    assert len(replay["applied_changes_pct"]) >= 10
    assert client.post("/simulate", json={"budget_id": "FY2019-20", "preset": "nope"}).status_code == 400
    assert client.post("/simulate", json={"budget_id": "FY2019-20", "changes": {"nope": 5}}).status_code == 400
    assert client.post("/simulate", json={"budget_id": "FY2019-20", "changes": {"defence": 500}}).status_code == 400
    for locked in LOCKED:
        assert client.post("/simulate", json={"budget_id": locked}).status_code == 400  # hold-out and live year are never loaded


# ---------------------------------------------------------------- cache and latency
def test_second_request_is_a_cache_hit_and_identical(client: TestClient) -> None:
    app = create_app(ROOT, MemoryCache())
    c = TestClient(app)
    first, second = c.get("/budgets/FY2023-24/forecast"), c.get("/budgets/FY2023-24/forecast")
    assert first.headers["x-cache"] == "miss" and second.headers["x-cache"] == "hit" and first.json() == second.json()


def test_memory_cache_expires_and_redis_cache_works_with_fakeredis_and_survives_an_outage() -> None:
    import fakeredis

    calls = []
    mem = MemoryCache()
    assert mem.get_or_set("k", 1, lambda: calls.append(1) or 5) == (5, False) and mem.get_or_set("k", 1, lambda: 6) == (5, True)
    time.sleep(1.1)
    assert mem.get_or_set("k", 1, lambda: 7) == (7, False)
    cache = RedisCache(fakeredis.FakeRedis())
    assert cache.get_or_set("a", 60, lambda: {"x": 1}) == ({"x": 1}, False) and cache.get_or_set("a", 60, lambda: {"x": 2}) == ({"x": 1}, True)

    class Broken:
        def get(self, *a, **k):
            raise ConnectionError("down")

    down = RedisCache(Broken())
    assert down.get_or_set("b", 60, lambda: 3) == (3, False) and down.get_or_set("b", 60, lambda: 4) == (3, True)
    assert isinstance(make_cache("redis://127.0.0.1:1/0"), MemoryCache) and isinstance(make_cache(""), MemoryCache)


def test_cached_forecast_latency_p95_is_far_below_500_ms() -> None:
    c = TestClient(create_app(ROOT, MemoryCache()))
    urls = ["/budgets/FY2023-24/forecast", "/sectors/defence/forecast?budget_id=FY2023-24", "/sectors", "/stocks?budget_id=FY2023-24"]
    for u in urls:
        c.get(u)  # warm
    times = []
    for _ in range(40):
        for u in urls:
            t = time.perf_counter()
            assert c.get(u).status_code == 200
            times.append(time.perf_counter() - t)
    assert np.percentile(times, 95) < 0.5


def test_the_api_never_reads_locked_budget_predictions() -> None:
    detail = pd.read_csv(ROOT / "reports" / "predictions_detail.csv")
    assert not set(detail["budget_id"]) & set(LOCKED)
