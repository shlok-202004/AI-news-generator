import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

import httpx

from config import (
    NEWSAPI_KEY,
    CATEGORIES,
    NEWSAPI_MAX_PER_CATEGORY,
    MAX_AGE_HOURS,
)

logger = logging.getLogger(__name__)

NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"


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
        # Guarantee description is never None
        self.description = self.description or ""


def _parse_newsapi_dt(dt_str: str | None) -> datetime | None:
    """Parse ISO 8601 string returned by NewsAPI into UTC datetime."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_fresh(published_at: datetime | None) -> bool:
    """Return True if the article is within MAX_AGE_HOURS."""
    if published_at is None:
        return True  # keep if we can't determine age
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    return published_at >= cutoff


def fetch_newsapi(category: str) -> list[Article]:
    """
    Fetch articles from NewsAPI for a given category key.

    Returns a list of Article objects sorted newest-first.
    Returns empty list on any error (non-raising — caller decides what to do).
    """
    cfg = CATEGORIES.get(category)
    if not cfg:
        logger.warning("fetch_newsapi: unknown category '%s'", category)
        return []

    from_dt = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = {
        "q":          cfg["newsapi_query"],
        "language":   cfg.get("newsapi_lang", "en"),
        "sortBy":     "publishedAt",
        "pageSize":   NEWSAPI_MAX_PER_CATEGORY,
        "from":       from_dt,
        "apiKey":     NEWSAPI_KEY,
    }

    try:
        response = httpx.get(NEWSAPI_ENDPOINT, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "NewsAPI HTTP %s for category '%s': %s",
            exc.response.status_code, category, exc.response.text[:200],
        )
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("NewsAPI fetch failed for category '%s': %s", category, exc)
        return []

    articles: list[Article] = []

    for raw in data.get("articles", []):
        url = raw.get("url", "")

        # NewsAPI returns a placeholder for removed articles
        if not url or url == "https://removed.com":
            continue

        title = (raw.get("title") or "").strip()
        if not title or title == "[Removed]":
            continue

        published_at = _parse_newsapi_dt(raw.get("publishedAt"))
        if not _is_fresh(published_at):
            continue

        articles.append(
            Article(
                id="",                              # filled by deduplicator
                title=title,
                url=url,
                source=raw.get("source", {}).get("name", "NewsAPI"),
                category=category,
                published_at=published_at or datetime.now(timezone.utc),
                description=raw.get("description") or raw.get("content") or "",
            )
        )

    logger.info(
        "NewsAPI › %s: fetched %d fresh article(s)", category, len(articles)
    )
    return articles


def fetch_all_newsapi() -> list[Article]:
    """Fetch NewsAPI articles for every configured category."""
    all_articles: list[Article] = []
    for category in CATEGORIES:
        all_articles.extend(fetch_newsapi(category))
    return all_articles
