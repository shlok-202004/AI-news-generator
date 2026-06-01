import hashlib
import logging
import re
import sqlite3
from datetime import datetime, timezone, timedelta

from config import DB_PATH
from fetchers.gnews_fetcher import Article

logger = logging.getLogger(__name__)

# Articles stay in the seen-store for this many days before expiry
SEEN_TTL_DAYS = 3

# Jaccard similarity threshold above which two titles are considered
# the same story from different sources
TITLE_SIMILARITY_THRESHOLD = 0.55


# ── DB bootstrap ───────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # safe concurrent access
    return conn


def init_db() -> None:
    """Create the seen_articles table if it doesn't exist."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_articles (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                url        TEXT NOT NULL,
                category   TEXT NOT NULL,
                seen_at    TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_seen_at ON seen_articles(seen_at)"
        )
        conn.commit()
    logger.debug("DB initialised at %s", DB_PATH)


def _purge_expired() -> None:
    """Remove rows older than SEEN_TTL_DAYS to keep the DB lean."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=SEEN_TTL_DAYS)
    ).isoformat()
    with _get_conn() as conn:
        deleted = conn.execute(
            "DELETE FROM seen_articles WHERE seen_at < ?", (cutoff,)
        ).rowcount
        conn.commit()
    if deleted:
        logger.info("Purged %d expired seen-article record(s)", deleted)


# ── Fingerprinting ─────────────────────────────────────────────────────────────

def _url_id(url: str) -> str:
    """Stable SHA-1 of the normalised URL (strip query params / fragments)."""
    # strip tracking params: everything after ? or #
    clean = re.split(r"[?#]", url.strip().lower())[0].rstrip("/")
    return hashlib.sha1(clean.encode()).hexdigest()


def _tokenise(title: str) -> set[str]:
    """
    Lowercase, strip punctuation, remove common stopwords.
    Returns a set of meaningful tokens for Jaccard comparison.
    """
    stopwords = {
        "a", "an", "the", "is", "in", "on", "at", "to", "of",
        "and", "or", "for", "with", "by", "as", "its", "it",
        "this", "that", "are", "was", "be", "has", "have",
    }
    tokens = re.findall(r"[a-z0-9]+", title.lower())
    return {t for t in tokens if t not in stopwords and len(t) > 1}


def _jaccard(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


# ── Main deduplication logic ───────────────────────────────────────────────────

def deduplicate(articles: list[Article]) -> list[Article]:
    """
    Pipeline:
      1. Assign SHA-1 IDs to all articles.
      2. Purge expired records from DB.
      3. Drop articles whose ID is already in the seen-store (exact URL dup).
      4. Drop near-duplicate titles within the current batch using Jaccard
         similarity (same story, different source).
      5. Return the surviving articles (does NOT mark them as seen yet —
         call mark_as_seen() after the full pipeline succeeds).
    """
    init_db()
    _purge_expired()

    # Step 1 — assign IDs
    for article in articles:
        article.id = _url_id(article.url)

    # Step 2 — load already-seen IDs from DB
    with _get_conn() as conn:
        rows = conn.execute("SELECT id FROM seen_articles").fetchall()
    seen_ids: set[str] = {row["id"] for row in rows}

    # Step 3 — exact URL dedup against DB
    after_db_dedup = [a for a in articles if a.id not in seen_ids]
    dropped_db = len(articles) - len(after_db_dedup)
    if dropped_db:
        logger.info("Dedup: dropped %d already-seen article(s)", dropped_db)

    # Step 4 — intra-batch fuzzy title dedup
    # Sort newest-first so we keep the most recent version of a story
    after_db_dedup.sort(key=lambda a: a.published_at, reverse=True)

    seen_token_sets: list[set[str]] = []
    unique_articles: list[Article] = []

    for article in after_db_dedup:
        tokens = _tokenise(article.title)
        is_dup = any(
            _jaccard(tokens, seen_set) >= TITLE_SIMILARITY_THRESHOLD
            for seen_set in seen_token_sets
        )
        if is_dup:
            logger.debug("Fuzzy dup dropped: %s", article.title[:80])
            continue
        seen_token_sets.append(tokens)
        unique_articles.append(article)

    dropped_fuzzy = len(after_db_dedup) - len(unique_articles)
    if dropped_fuzzy:
        logger.info(
            "Dedup: dropped %d near-duplicate title(s)", dropped_fuzzy
        )

    logger.info(
        "Dedup: %d → %d unique article(s)",
        len(articles), len(unique_articles),
    )
    return unique_articles


def mark_as_seen(articles: list[Article]) -> None:
    """
    Persist article IDs to the seen-store.
    Call this ONLY after the full pipeline (fetch → dedup → AI → deliver)
    succeeds, so a failed run retries the same articles next time.
    """
    if not articles:
        return
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (a.id, a.title[:255], a.url[:1024], a.category, now)
        for a in articles
    ]
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO seen_articles (id, title, url, category, seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    logger.info("Marked %d article(s) as seen", len(rows))
