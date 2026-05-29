"""
processor/trend_tracker.py — Detect trending and returning stories.

Compares each article's title against stored history.
Tags articles that have been seen before so the AI can label them.
"""

import hashlib
import logging
import re

from fetchers.gnews_fetcher import Article
from db.store import get_story_count, init_tables, purge_old_stories, upsert_story

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "a", "an", "the", "is", "in", "on", "at", "to", "of",
    "and", "or", "for", "with", "by", "as", "its", "it",
    "this", "that", "are", "was", "be", "has", "have",
}


def _title_hash(title: str) -> str:
    tokens = sorted(
        t for t in re.findall(r"[a-z0-9]+", title.lower())
        if t not in _STOPWORDS and len(t) > 2
    )
    return hashlib.sha1(" ".join(tokens).encode()).hexdigest()


def tag_trending(articles: list[Article]) -> list[Article]:
    """
    Check each article against story history and prepend a trend tag
    to article.description so the AI naturally surfaces it.

    Tags:
        [🔥 TRENDING — Day N]  — story appearing for the 3rd+ time
        [📌 UPDATE]            — story seen once before (2nd appearance)

    Mutates articles in-place and returns the same list.
    """
    init_tables()
    purge_old_stories()

    trending = 0
    updates  = 0

    for article in articles:
        h          = _title_hash(article.title)
        prev_count = get_story_count(h)
        new_count  = upsert_story(h, article.title, article.category)

        if prev_count == 0:
            continue  # brand-new story — no tag

        if new_count >= 3:
            tag      = f"[🔥 TRENDING — Day {new_count}] "
            trending += 1
        else:
            tag     = "[📌 UPDATE] "
            updates += 1

        article.description = tag + article.description
        logger.debug("Trend tag applied: %s → %s", tag.strip(), article.title[:60])

    if trending or updates:
        logger.info(
            "Trend tracker: %d trending, %d updates out of %d articles",
            trending, updates, len(articles),
        )
    return articles
