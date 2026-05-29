import logging
import time
from datetime import datetime, timezone, timedelta

import feedparser

from config import CATEGORIES, RSS_MAX_PER_FEED, MAX_AGE_HOURS
from fetchers.gnews_fetcher import Article

logger = logging.getLogger(__name__)


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


def fetch_rss_for_category(category: str) -> list[Article]:
    """Fetch all RSS feeds configured for a single category."""
    cfg = CATEGORIES.get(category)
    if not cfg:
        logger.warning("fetch_rss_for_category: unknown category '%s'", category)
        return []

    articles: list[Article] = []
    for feed_url in cfg.get("rss_feeds", []):
        articles.extend(fetch_rss_feed(feed_url, category))

    return articles


def fetch_all_rss() -> list[Article]:
    """Fetch RSS feeds for every configured category."""
    all_articles: list[Article] = []
    for category in CATEGORIES:
        all_articles.extend(fetch_rss_for_category(category))
    return all_articles
