"""The scheduler registers the two recurring ingestion jobs with the intended triggers (nothing is started)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from bsp.ingest import scheduler as sched

IST = ZoneInfo("Asia/Kolkata")


def _fields(job) -> dict[str, str]:
    return {f.name: str(f) for f in job.trigger.fields}


def test_jobs_are_registered_with_expected_ids_and_single_instance() -> None:
    scheduler = sched.build_scheduler()
    assert not scheduler.running
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {sched.PRICES_JOB_ID, sched.FPI_JOB_ID}
    assert all(job.max_instances == 1 and job.coalesce for job in jobs.values())


def test_daily_prices_runs_weekdays_after_market_close() -> None:
    job = sched.build_scheduler().get_job(sched.PRICES_JOB_ID)
    f = _fields(job)
    assert (f["day_of_week"], f["hour"], f["minute"]) == ("mon-fri", "18", "30")
    saturday = datetime(2026, 10, 24, 12, 0, tzinfo=IST)
    nxt = job.trigger.get_next_fire_time(None, saturday)
    assert nxt.weekday() == 0 and (nxt.hour, nxt.minute) == (18, 30)  # skips the weekend


def test_fortnightly_fpi_runs_on_1st_and_16th() -> None:
    job = sched.build_scheduler().get_job(sched.FPI_JOB_ID)
    assert _fields(job)["day"] == "1,16"
    now = datetime(2026, 10, 2, 0, 0, tzinfo=IST)
    first = job.trigger.get_next_fire_time(None, now)
    second = job.trigger.get_next_fire_time(first, first)
    assert (first.day, second.month, second.day) == (16, 11, 1)


def test_jobs_call_the_idempotent_collectors(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sched, "collect_prices", lambda: calls.append("prices") or [])
    monkeypatch.setattr(sched, "collect_fpi", lambda: calls.append("fpi") or [])
    scheduler = sched.build_scheduler()
    for job_id in (sched.PRICES_JOB_ID, sched.FPI_JOB_ID):
        scheduler.get_job(job_id).func()
    assert calls == ["prices", "fpi"]
