"""APScheduler job definitions for recurring ingestion (README Phase 2).

``build_scheduler()`` only registers the jobs; nothing runs until ``start()`` is called, so it is safe to
import and unit-test. Jobs are the same idempotent collectors used by ``make collect``.

Run as a blocking process: ``python -m bsp.ingest.scheduler``.
"""

from __future__ import annotations

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from bsp.common.logging import get_logger
from bsp.ingest.fpi import collect_fpi
from bsp.ingest.prices import collect_prices

TIMEZONE = "Asia/Kolkata"
PRICES_JOB_ID = "daily_prices"
FPI_JOB_ID = "fortnightly_fpi"

logger = get_logger(__name__)


def _run_prices() -> None:
    frame = collect_prices()
    logger.info("daily prices job finished: %s rows", len(frame))


def _run_fpi() -> None:
    frame = collect_fpi()
    logger.info("fortnightly FPI job finished: %s rows", len(frame))


def register_jobs(scheduler: BaseScheduler) -> BaseScheduler:
    """Daily prices after the Indian market close (Mon-Fri); FPI on the 1st and 16th, after each fortnight ends.

    ``collect_fpi`` walks every fortnight and caches pages already downloaded, so a page NSDL has not
    published yet is simply fetched by the next run. Overlapping runs are skipped (``max_instances=1``).
    """
    scheduler.add_job(
        _run_prices,
        CronTrigger(day_of_week="mon-fri", hour=18, minute=30, timezone=TIMEZONE),
        id=PRICES_JOB_ID,
        name="Daily Yahoo prices",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_fpi,
        CronTrigger(day="1,16", hour=9, minute=0, timezone=TIMEZONE),
        id=FPI_JOB_ID,
        name="Fortnightly NSDL FPI sector flows",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    return scheduler


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    register_jobs(scheduler)
    return scheduler


def main() -> None:  # pragma: no cover - blocking entry point
    build_scheduler().start()


if __name__ == "__main__":
    main()
