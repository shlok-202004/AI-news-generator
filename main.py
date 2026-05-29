"""
main.py — Daily News Briefing Pipeline

Run manually:
    python main.py            # full run → sends to Discord
    python main.py --dry-run  # prints briefing to stdout, no Discord

The same functions are imported by scheduler.py and discord_bot.py.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta

from fetchers import fetch_all_gnews, fetch_all_rss
from fetchers.scraper import enrich_articles
from processor import deduplicate, mark_as_seen, rank_and_select
from processor.trend_tracker import tag_trending
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
    for noisy in ("httpx", "httpcore", "telegram", "apscheduler", "trafilatura"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ── Shared pipeline core ────────────────────────────────────────────────────────

def _fetch_filter_scrape(
    category: str | None = None,
    limit: int | None = None,
) -> tuple[dict, list]:
    """
    Steps 1-4: fetch → dedup → filter → scrape.
    Returns (selected_articles_by_category, all_unique_articles).
    If category is given, only that category is kept after filtering.
    limit=None passes all ranked articles to AI (used by /news).
    limit=N caps per category (used by the scheduled pipeline).
    """
    # Fetch
    gnews_articles = fetch_all_gnews()
    rss_articles   = fetch_all_rss()
    all_articles   = gnews_articles + rss_articles
    logger.info(
        "Fetched %d total (GNews: %d, RSS: %d)",
        len(all_articles), len(gnews_articles), len(rss_articles),
    )

    if not all_articles:
        raise RuntimeError("No articles fetched — aborting")

    # Dedup
    unique = deduplicate(all_articles)
    if not unique:
        raise RuntimeError("All articles were duplicates — nothing new")

    # Filter & rank
    selected = rank_and_select(unique, limit=limit)
    if not selected:
        raise RuntimeError("Filter returned empty selection")

    logger.info(
        "Selected %d articles across %d categories",
        sum(len(v) for v in selected.values()), len(selected),
    )

    # Optional single-category filter (for slash commands)
    if category:
        matched = next(
            (k for k in selected if category.lower() in k.lower()), None
        )
        if not matched:
            raise ValueError(f"Category '{category}' not found or has no articles today")
        selected = {matched: selected[matched]}

    # Scrape full article text
    logger.info("Scraping full article text…")
    selected = enrich_articles(selected)

    # Tag trending / returning stories
    all_selected = [a for arts in selected.values() for a in arts]
    tag_trending(all_selected)

    return selected, unique


def build_sections(category: str | None = None, limit: int | None = None) -> list[str]:
    """
    Run the pipeline up to AI generation and return briefing sections.
    Does NOT deliver or mark articles as seen — safe to call from the bot.
    limit=None sends every fetched article to the AI (used by /news).
    limit=N caps articles per category (used by the scheduler).
    """
    selected, _ = _fetch_filter_scrape(category, limit=limit)
    from config import AI_PROVIDER
    logger.info("Generating briefing with %s…", AI_PROVIDER.upper())
    return generate_briefing(selected)


# ── Full pipeline (scheduler entry point) ──────────────────────────────────────

def run_pipeline(dry_run: bool = False, deliver: bool = True) -> list[str]:
    """
    Full pipeline:
      1. Fetch  — GNews + RSS for all categories
      2. Dedup  — remove seen / near-duplicate articles
      3. Filter — score & select top N per category
      4. Scrape — fetch full article text
      5. AI     — generate briefing
      6. Deliver — send to Discord (or stdout if dry_run)
      7. Commit  — mark articles as seen in SQLite

    deliver=False skips the webhook send (used by the Discord bot, which posts
    the briefing itself with reactions) while still generating and marking seen.
    """
    ist = timezone(timedelta(hours=5, minutes=30))
    start = datetime.now(ist)
    logger.info("━━━ Pipeline started at %s ━━━", start.strftime("%H:%M IST"))

    from config import TOP_ARTICLES_FOR_AI
    selected, unique = _fetch_filter_scrape(limit=TOP_ARTICLES_FOR_AI)

    from config import AI_PROVIDER
    logger.info("Generating briefing with %s…", AI_PROVIDER.upper())
    sections = generate_briefing(selected)
    logger.info("Briefing: %d section(s) ready", len(sections))

    if deliver:
        logger.info("Delivering to Discord… (dry_run=%s)", dry_run)
        send_briefing(sections, dry_run=dry_run)
    else:
        logger.info("Skipping webhook delivery (deliver=False)")

    # Only reached if delivery succeeded — guarantees retry on failure
    if not dry_run:
        logger.info("Marking articles as seen…")
        mark_as_seen(unique)

    elapsed = (datetime.now(ist) - start).total_seconds()
    logger.info("━━━ Pipeline complete in %.1fs ━━━", elapsed)
    return sections


# ── CLI entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    os.makedirs("logs", exist_ok=True)

    _setup_logging()

    parser = argparse.ArgumentParser(description="Daily News Briefing Pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print briefing to stdout instead of sending to Discord",
    )
    args = parser.parse_args()

    try:
        run_pipeline(dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        sys.exit(1)
