import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

from fetchers.gnews_fetcher import Article
from config import CATEGORIES, TOP_ARTICLES_FOR_AI

logger = logging.getLogger(__name__)


# ── Source tier scoring ────────────────────────────────────────────────────────
# Tier 1 sources are more reliable / signal-rich.
# Partial match: if any string below appears in the source name (lowercased),
# the article gets the corresponding bonus.

_SOURCE_TIERS: list[tuple[int, list[str]]] = [
    (30, ["reuters", "bbc", "bloomberg", "ft.com", "financial times",
          "associated press", "ap news", "the hindu", "indian express",
          "cnbc", "guardian", "npr", "nikkei", "politico"]),
    (20, ["techcrunch", "wired", "ars technica", "the verge", "mit technology",
          "venture beat", "ndtv", "al jazeera", "variety", "deadline",
          "stat news", "statnews", "the hill", "defenseone", "breaking defense",
          "electrek", "inside evs", "sky sports", "fortune", "fast company",
          "business insider", "crunchbase", "inside climate", "science daily",
          "space.com", "hacker news", "bleeping computer", "krebs on security",
          "ign", "polygon", "kotaku", "digiday", "nieman"]),
    (10, ["yahoo finance", "google news", "newsapi", "healthline",
          "campus technology"]),
]

def _source_score(source: str) -> int:
    sl = source.lower()
    for score, names in _SOURCE_TIERS:
        if any(n in sl for n in names):
            return score
    return 5  # unknown source gets a small baseline


# ── Recency scoring ────────────────────────────────────────────────────────────
# Linear decay: article published now → 40 pts; 24 h ago → 0 pts

def _recency_score(published_at: datetime) -> float:
    age_hours = (
        datetime.now(timezone.utc) - published_at
    ).total_seconds() / 3600
    age_hours = max(0.0, min(age_hours, 24.0))
    return 40.0 * (1.0 - age_hours / 24.0)


# ── Description quality scoring ────────────────────────────────────────────────
# Reward articles that carry useful context beyond the headline.

def _description_score(description: str) -> int:
    length = len(description.strip())
    if length > 300:
        return 20
    if length > 100:
        return 10
    if length > 0:
        return 5
    return 0


# ── Title quality scoring ──────────────────────────────────────────────────────
# Penalise clickbait (very short) and bloated titles.

def _title_score(title: str) -> int:
    word_count = len(title.split())
    if 6 <= word_count <= 18:
        return 10
    if 4 <= word_count <= 25:
        return 5
    return 0


# ── Clickbait / low-quality signal penalties ──────────────────────────────────
_CLICKBAIT_PATTERNS = re.compile(
    r"\b(you won't believe|shocking|insane|jaw.drop|must.see|"
    r"what happened next|number \d+ will|click here|WATCH:)\b",
    re.IGNORECASE,
)

def _quality_penalty(title: str, description: str) -> int:
    text = title + " " + description
    if _CLICKBAIT_PATTERNS.search(text):
        return -20
    return 0


# ── Master scorer ──────────────────────────────────────────────────────────────

def score_article(article: Article) -> float:
    return (
        _source_score(article.source)
        + _recency_score(article.published_at)
        + _description_score(article.description)
        + _title_score(article.title)
        + _quality_penalty(article.title, article.description)
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def rank_and_select(
    articles: list[Article],
    limit: int | None = TOP_ARTICLES_FOR_AI,
) -> dict[str, list[Article]]:
    """
    Group articles by category, score each one, and sort descending.
    limit=N  → return top N per category (scheduled briefing default).
    limit=None → return all ranked articles (used by /news slash command).

    Returns:
        {category_name: [Article, ...]}  — only categories with ≥1 article.
    """
    grouped: dict[str, list[Article]] = defaultdict(list)
    for article in articles:
        grouped[article.category].append(article)

    selected: dict[str, list[Article]] = {}

    for category in CATEGORIES:  # iterate in config order for consistent output
        bucket = grouped.get(category, [])
        if not bucket:
            logger.warning("No articles found for category '%s'", category)
            continue

        scored = sorted(bucket, key=score_article, reverse=True)
        top = scored[:limit] if limit is not None else scored

        logger.info(
            "Filter › %s: %d article(s) → %d selected",
            category, len(bucket), len(top),
        )
        selected[category] = top

    return selected
