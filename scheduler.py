"""
scheduler.py — Keeps the pipeline running on a daily cron schedule.

Run:
    python scheduler.py

Runs the briefing every day at 08:00 IST.
Keeps the process alive — deploy with systemd, screen, or tmux.
"""

import logging
import sys
import os
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/scheduler.log", encoding="utf-8"),
    ],
)
for noisy in ("httpx", "httpcore", "telegram", "apscheduler.executors"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Import here (after logging is set up) so config errors surface cleanly
from main import run_pipeline  # noqa: E402


# ── Job event listener ─────────────────────────────────────────────────────────

def _on_job_event(event: JobExecutionEvent) -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist).strftime("%H:%M IST")

    if event.exception:
        logger.error(
            "Job '%s' FAILED at %s: %s", event.job_id, now, event.exception
        )
    else:
        logger.info("Job '%s' completed successfully at %s", event.job_id, now)


# ── Scheduled job ──────────────────────────────────────────────────────────────

def scheduled_run() -> None:
    """Wrapper so APScheduler can call run_pipeline safely."""
    try:
        run_pipeline(dry_run=False)
    except Exception as exc:
        # Log here too — APScheduler catches exceptions but this gives context
        logger.exception("Scheduled pipeline raised an exception: %s", exc)
        raise  # re-raise so APScheduler records the failure in the event


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    # Cron: every day at 08:00 IST
    # Change hour/minute here to adjust delivery time
    trigger = CronTrigger(
        hour=8,
        minute=0,
        timezone="Asia/Kolkata",
    )

    scheduler.add_job(
        scheduled_run,
        trigger=trigger,
        id="daily_briefing",
        name="Daily News Briefing",
        max_instances=1,        # never run two overlapping pipelines
        misfire_grace_time=600, # if delayed by up to 10 min, still run
        coalesce=True,          # if multiple missed, run only once on recovery
    )

    scheduler.add_listener(
        _on_job_event,
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
    )

    ist = timezone(timedelta(hours=5, minutes=30))
    logger.info(
        "Scheduler started — daily briefing at 08:00 IST "
        "(current time: %s)",
        datetime.now(ist).strftime("%H:%M IST, %d %b %Y"),
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
        scheduler.shutdown(wait=False)
        sys.exit(0)
