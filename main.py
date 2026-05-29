"""
main.py — Daily News Briefing Pipeline

Run manually:
    python main.py            # full run → sends to Telegram
    python main.py --dry-run  # prints briefing to stdout, no Telegram

The same run_pipeline() function is imported by scheduler.py.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta

from fetchers import fetch_all_gnews, fetch_all_rss
from processor import deduplicate, mark_as_seen, rank_and_select
from ai import generate_briefing
from delivery import send_briefing

# ── Logging setup ──────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    log_time = datetime.now(ist).strftime("%Y-%m-%d_%H-%M")

    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f"logs/briefing_{log_time}.log", encoding="utf-8"),
        ],
    )
    # Quieten noisy third-party loggers
    for noisy in ("httpx", "httpcore", "telegram", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ── Pipeline ───────────────────────────────────────────────────────────────────

def run_pipeline(dry_run: bool = False) -> None:
    """
    Full pipeline:
      1. Fetch  — NewsAPI + RSS for all categories
      2. Dedup  — remove seen / near-duplicate articles
      3. Filter — score & select top N per category
      4. AI     — generate briefing via Claude
      5. Deliver — send to Telegram (or stdout if dry_run)
      6. Commit — mark articles as seen in SQLite
    """
    ist = timezone(timedelta(hours=5, minutes=30))
    start = datetime.now(ist)
    logger.info("━━━ Pipeline started at %s ━━━", start.strftime("%H:%M IST"))

    # ── Step 1: Fetch ──────────────────────────────────────────────────────────
    logger.info("[1/6] Fetching articles…")
    gnews_articles = fetch_all_gnews()
    rss_articles   = fetch_all_rss()
    all_articles   = gnews_articles + rss_articles

    logger.info(
        "Fetched %d total (GNews: %d, RSS: %d)",
        len(all_articles), len(gnews_articles), len(rss_articles),
    )

    if not all_articles:
        logger.error("No articles fetched — aborting pipeline")
        return

    # ── Step 2: Deduplicate ────────────────────────────────────────────────────
    logger.info("[2/6] Deduplicating…")
    unique_articles = deduplicate(all_articles)

    if not unique_articles:
        logger.warning("All articles were duplicates — nothing new today")
        return

    # ── Step 3: Filter & rank ──────────────────────────────────────────────────
    logger.info("[3/6] Scoring and selecting top articles…")
    selected = rank_and_select(unique_articles)

    if not selected:
        logger.error("Filter returned empty selection — aborting")
        return

    logger.info(
        "Selected %d articles across %d categories",
        sum(len(v) for v in selected.values()), len(selected),
    )

    # ── Step 4: Generate briefing ──────────────────────────────────────────────
    from config import AI_PROVIDER
    logger.info("[4/6] Generating briefing with %s…", AI_PROVIDER.upper())
    sections = generate_briefing(selected)
    logger.info("Briefing: %d section(s) ready", len(sections))

    # ── Step 5: Deliver ────────────────────────────────────────────────────────
    logger.info("[5/6] Delivering to Discord… (dry_run=%s)", dry_run)
    send_briefing(sections, dry_run=dry_run)

    # ── Step 6: Commit seen articles ───────────────────────────────────────────
    # Only reached if delivery succeeded — guarantees retry on failure
    logger.info("[6/6] Marking articles as seen…")
    mark_as_seen(unique_articles)

    elapsed = (datetime.now(ist) - start).total_seconds()
    logger.info("━━━ Pipeline complete in %.1fs ━━━", elapsed)


# ── CLI entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    os.makedirs("logs", exist_ok=True)

    _setup_logging()

    parser = argparse.ArgumentParser(description="Daily News Briefing Pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print briefing to stdout instead of sending to Telegram",
    )
    args = parser.parse_args()

    try:
        run_pipeline(dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as exc:
        logger.exception("Pipeline failed with unhandled exception: %s", exc)
        sys.exit(1)
