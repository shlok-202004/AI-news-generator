import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

import httpx

from config import (
    GNEWS_API_KEY,
    CATEGORIES,
    GNEWS_MAX_PER_CATEGORY,
    MAX_AGE_HOURS,
)

logger = logging.getLogger(__name__)

GNEWS_ENDPOINT = "https://gnews.io/api/v4/search"


@dataclass
class Article:
    """Normalised article object shared across fetchers."""
    id: str           # sha1 of url — set by deduplicator
    title: str
    url: str
    source: str
    category: str
    published_at: datetime
    description: str = ""

    def __post_init__(self):
        self.description = self.description or ""


def _parse_gnews_dt(dt_str: str | None) -> datetime | None:
    """GNews returns ISO 8601 with timezone offset, e.g. 2025-05-29T10:00:00Z"""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_fresh(published_at: datetime | None) -> bool:
    if published_at is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    return published_at >= cutoff


def fetch_gnews(category: str) -> list[Article]:
    """
    Fetch articles from GNews API for a given category key.
    GNews free tier: 100 req/day, max 10 articles/request, no content delay.
    Returns empty list on any error.
    """
    cfg = CATEGORIES.get(category)
    if not cfg:
        logger.warning("fetch_gnews: unknown category '%s'", category)
        return []

    from_dt = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    params = {
        "q":      cfg["gnews_query"],
        "lang":   cfg.get("gnews_lang", "en"),
        "max":    GNEWS_MAX_PER_CATEGORY,
        "from":   from_dt,
        "sortby": "publishedAt",
        "apikey": GNEWS_API_KEY,
    }

    try:
        response = httpx.get(GNEWS_ENDPOINT, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "GNews HTTP %s for category '%s': %s",
            exc.response.status_code, category, exc.response.text[:300],
        )
        return []
    except Exception as exc:
        logger.error("GNews fetch failed for category '%s': %s", category, exc)
        return []

    articles: list[Article] = []

    for raw in data.get("articles", []):
        url = (raw.get("url") or "").strip()
        title = (raw.get("title") or "").strip()

        if not url or not title:
            continue

        published_at = _parse_gnews_dt(raw.get("publishedAt"))
        if not _is_fresh(published_at):
            continue

        articles.append(
            Article(
                id="",
                title=title,
                url=url,
                source=raw.get("source", {}).get("name", "GNews"),
                category=category,
                published_at=published_at or datetime.now(timezone.utc),
                description=raw.get("description") or raw.get("content") or "",
            )
        )

    logger.info("GNews › %s: fetched %d fresh article(s)", category, len(articles))
    return articles


def fetch_all_gnews() -> list[Article]:
    """Fetch GNews articles for every configured category."""
    all_articles: list[Article] = []
    for category in CATEGORIES:
        all_articles.extend(fetch_gnews(category))
    return all_articles


def fetch_topic(query: str, max_results: int = 10, hours: int = 48) -> list[Article]:
    """
    Fetch articles about any free-form topic from the last `hours` hours.
    Used by the /summary slash command.
    """
    from_dt = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = {
        "q":      query,
        "lang":   "en",
        "max":    max_results,
        "from":   from_dt,
        "sortby": "publishedAt",
        "apikey": GNEWS_API_KEY,
    }
    try:
        response = httpx.get(GNEWS_ENDPOINT, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.error("GNews topic fetch failed for '%s': %s", query, exc)
        return []

    articles: list[Article] = []
    for raw in data.get("articles", []):
        url   = (raw.get("url")   or "").strip()
        title = (raw.get("title") or "").strip()
        if not url or not title:
            continue
        published_at = _parse_gnews_dt(raw.get("publishedAt"))
        articles.append(Article(
            id="",
            title=title,
            url=url,
            source=raw.get("source", {}).get("name", "GNews"),
            category="_topic",
            published_at=published_at or datetime.now(timezone.utc),
            description=raw.get("description") or raw.get("content") or "",
        ))

    logger.info("GNews topic '%s': fetched %d article(s)", query, len(articles))
    return articles
