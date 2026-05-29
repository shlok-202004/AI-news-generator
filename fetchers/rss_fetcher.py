import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import feedparser

from config import CATEGORIES, RSS_MAX_PER_FEED, MAX_AGE_HOURS
from fetchers.gnews_fetcher import Article

logger = logging.getLogger(__name__)

# Parallel feed downloads — feedparser.parse() is a blocking network call,
# so fetching feeds concurrently cuts wall-clock time on the slowest stage.
_RSS_WORKERS = 8


def _parse_rss_dt(entry: feedparser.FeedParserDict) -> datetime | None:
    """
    feedparser exposes parsed_published / updated_parsed as a time.struct_time.
    Convert it to a UTC-aware datetime. Falls back to None gracefully.
    """
    struct = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )
    if struct is None:
        return None
    try:
        return datetime.fromtimestamp(time.mktime(struct), tz=timezone.utc)
    except (OverflowError, ValueError):
        return None


def _is_fresh(published_at: datetime | None) -> bool:
    if published_at is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    return published_at >= cutoff


def fetch_rss_feed(feed_url: str, category: str) -> list[Article]:
    """
    Parse a single RSS/Atom feed URL and return fresh articles.

    feedparser never raises — it returns an empty feed on network failure,
    so we check bozo_exception for soft errors.
    """
    parsed = feedparser.parse(feed_url)

    if parsed.bozo and parsed.bozo_exception:
        # bozo = True means the feed is malformed, but entries may still exist
        logger.warning(
            "RSS bozo error for %s: %s", feed_url, parsed.bozo_exception
        )

    articles: list[Article] = []

    for entry in parsed.entries[:RSS_MAX_PER_FEED]:
        url = entry.get("link", "").strip()
        title = entry.get("title", "").strip()

        if not url or not title:
            continue

        published_at = _parse_rss_dt(entry)
        if not _is_fresh(published_at):
            continue

        # Best-effort description: summary → content → empty
        description = (
            entry.get("summary")
            or (entry.get("content") or [{}])[0].get("value")
            or ""
        ).strip()

        source = parsed.feed.get("title") or feed_url.split("/")[2]

        articles.append(
            Article(
                id="",
                title=title,
                url=url,
                source=source,
                category=category,
                published_at=published_at or datetime.now(timezone.utc),
                description=description,
            )
        )

    logger.info(
        "RSS › %s [%s]: fetched %d article(s)",
        category, feed_url.split("/")[2], len(articles),
    )
    return articles


def fetch_all_rss(categories: list[str] | None = None) -> list[Article]:
    """Fetch RSS feeds for configured categories, in parallel.
    Pass `categories` to restrict the fetch to specific category keys."""
    cat_items = (
        [(c, CATEGORIES[c]) for c in categories if c in CATEGORIES]
        if categories is not None
        else list(CATEGORIES.items())
    )
    # Flatten every (feed_url, category) pair so feeds across all categories
    # download concurrently rather than one category at a time.
    tasks = [
        (feed_url, category)
        for category, cfg in cat_items
        for feed_url in cfg.get("rss_feeds", [])
    ]
    if not tasks:
        return []

    all_articles: list[Article] = []
    with ThreadPoolExecutor(max_workers=_RSS_WORKERS) as pool:
        results = pool.map(lambda t: fetch_rss_feed(*t), tasks)
        for articles in results:
            all_articles.extend(articles)
    return all_articles
