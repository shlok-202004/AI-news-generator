import logging
from concurrent.futures import ThreadPoolExecutor
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

# ── Quota tracking ─────────────────────────────────────────────────────────────
# When a 429/403 is received the timestamp is recorded. Quota resets every 24h
# on GNews free tier, so we stop all GNews calls until the window expires.

_quota_exceeded_at: datetime | None = None


def _quota_exceeded() -> bool:
    if _quota_exceeded_at is None:
        return False
    return (datetime.now(timezone.utc) - _quota_exceeded_at).total_seconds() < 86_400


def _mark_quota_exceeded() -> None:
    global _quota_exceeded_at
    _quota_exceeded_at = datetime.now(timezone.utc)
    logger.warning(
        "GNews daily quota exhausted — switching to RSS-only mode. "
        "Quota resets in ~24 h (at %s UTC).",
        (_quota_exceeded_at + timedelta(hours=24)).strftime("%H:%M %d-%b"),
    )


def quota_status() -> str:
    """Human-readable quota status; used by the Discord bot for /stats."""
    if not _quota_exceeded():
        return "GNews API: ✅ available"
    resets_at = (_quota_exceeded_at + timedelta(hours=24)).strftime("%H:%M UTC %d %b")
    return f"GNews API: ⚠️ quota exhausted — RSS-only until {resets_at}"


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

    if _quota_exceeded():
        return []  # already in RSS-only mode; skip silently

    try:
        response = httpx.get(GNEWS_ENDPOINT, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (429, 403):
            _mark_quota_exceeded()
        else:
            logger.error(
                "GNews HTTP %s for category '%s': %s",
                status, category, exc.response.text[:300],
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


def fetch_all_gnews(categories: list[str] | None = None) -> list[Article]:
    """Fetch GNews articles for configured categories, in parallel.
    Pass `categories` to restrict the fetch to specific category keys
    (used by single-category /news so it doesn't hit all 25).
    Returns [] immediately if the daily quota is already exhausted."""
    if _quota_exceeded():
        logger.warning("GNews quota exhausted — skipping all GNews fetches (RSS-only mode)")
        return []
    cats = list(categories) if categories is not None else list(CATEGORIES)
    if not cats:
        return []
    # Cap concurrency: firing all categories at once can trip GNews' per-second
    # rate limit (429), which we'd misread as daily-quota exhaustion and lock
    # into RSS-only mode for 24h. A modest pool stays fast without the burst.
    with ThreadPoolExecutor(max_workers=min(len(cats), 8)) as pool:
        results = pool.map(fetch_gnews, cats)
    return [a for articles in results for a in articles]


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
