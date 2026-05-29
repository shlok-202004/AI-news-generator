import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import trafilatura

from fetchers.gnews_fetcher import Article

logger = logging.getLogger(__name__)

_MAX_CHARS = 2000   # characters of full text sent to AI
_TIMEOUT   = 8      # seconds per article fetch
_WORKERS   = 6      # parallel scrape threads


def _scrape_one(article: Article) -> tuple[Article, bool]:
    try:
        downloaded = trafilatura.fetch_url(article.url, timeout=_TIMEOUT)
        if not downloaded:
            return article, False
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if text and len(text) > 120:
            article.description = text[:_MAX_CHARS].strip()
            return article, True
        return article, False
    except Exception as exc:
        logger.debug("Scrape failed %s: %s", article.url[:70], exc)
        return article, False


def enrich_articles(selected: dict[str, list[Article]]) -> dict[str, list[Article]]:
    """
    Scrape full article text for every selected article in parallel.
    Falls back to the existing short description on failure.
    Mutates articles in-place and returns the same dict.
    """
    all_articles = [a for articles in selected.values() for a in articles]
    enriched = 0

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_scrape_one, a): a for a in all_articles}
        for future in as_completed(futures):
            _, success = future.result()
            if success:
                enriched += 1

    logger.info(
        "Scraper: enriched %d / %d articles with full text",
        enriched, len(all_articles),
    )
    return selected
