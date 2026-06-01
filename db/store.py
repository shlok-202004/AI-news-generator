"""
db/store.py — Centralised SQLite store for subscriptions, reactions, and story history.
All features share the same seen_articles.db file.
"""

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

from config import DB_PATH

logger = logging.getLogger(__name__)


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_tables() -> None:
    """Create all feature tables (idempotent)."""
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id  TEXT NOT NULL,
                category TEXT NOT NULL,
                PRIMARY KEY (user_id, category)
            );

            CREATE TABLE IF NOT EXISTS message_reactions (
                message_id  TEXT PRIMARY KEY,
                category    TEXT NOT NULL,
                thumbs_up   INTEGER DEFAULT 0,
                thumbs_down INTEGER DEFAULT 0,
                sent_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS story_history (
                title_hash       TEXT PRIMARY KEY,
                title            TEXT NOT NULL,
                category         TEXT NOT NULL,
                first_seen       TEXT NOT NULL,
                last_seen        TEXT NOT NULL,
                appearance_count INTEGER DEFAULT 1
            );
        """)
        c.commit()
    logger.debug("Feature tables initialised")


# ── Subscriptions ──────────────────────────────────────────────────────────────

def subscribe(user_id: str, category: str) -> bool:
    """Returns True if newly subscribed, False if already existed."""
    with _conn() as c:
        try:
            c.execute(
                "INSERT INTO subscriptions (user_id, category) VALUES (?, ?)",
                (str(user_id), category),
            )
            c.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def unsubscribe(user_id: str, category: str) -> bool:
    """Returns True if removed, False if wasn't subscribed."""
    with _conn() as c:
        rows = c.execute(
            "DELETE FROM subscriptions WHERE user_id=? AND category=?",
            (str(user_id), category),
        ).rowcount
        c.commit()
    return rows > 0


def get_subscriptions(user_id: str) -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT category FROM subscriptions WHERE user_id=?", (str(user_id),)
        ).fetchall()
    return [r["category"] for r in rows]


def get_all_subscriptions() -> dict[str, list[str]]:
    """{user_id: [category, ...]} for every subscriber."""
    with _conn() as c:
        rows = c.execute("SELECT user_id, category FROM subscriptions").fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["user_id"], []).append(row["category"])
    return result


# ── Reactions ──────────────────────────────────────────────────────────────────

def record_message(message_id: str, category: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO message_reactions (message_id, category, sent_at) VALUES (?, ?, ?)",
            (str(message_id), category, now),
        )
        c.commit()


def record_reaction(message_id: str, emoji: str) -> str | None:
    """
    Increments thumbs_up or thumbs_down for the message.
    Returns the category name, or None if the message isn't tracked.
    """
    col = {"👍": "thumbs_up", "👎": "thumbs_down"}.get(emoji)
    if not col:
        return None
    with _conn() as c:
        row = c.execute(
            f"UPDATE message_reactions SET {col}={col}+1 WHERE message_id=? RETURNING category",
            (str(message_id),),
        ).fetchone()
        c.commit()
    return row["category"] if row else None


def get_reaction_stats() -> list[dict]:
    """Reaction totals per category, sorted by total engagement."""
    with _conn() as c:
        rows = c.execute("""
            SELECT category,
                   SUM(thumbs_up)   AS thumbs_up,
                   SUM(thumbs_down) AS thumbs_down
            FROM message_reactions
            GROUP BY category
            ORDER BY (SUM(thumbs_up) + SUM(thumbs_down)) DESC
        """).fetchall()
    return [dict(r) for r in rows]


# ── Story history / trending ───────────────────────────────────────────────────

def upsert_story(title_hash: str, title: str, category: str) -> int:
    """
    Insert a new story or bump its appearance count.
    appearance_count tracks DISTINCT DAYS the story was seen, so repeat fetches
    on the same day (e.g. multiple /news calls) don't inflate the count.
    Returns the current count.
    """
    today = date.today().isoformat()
    with _conn() as c:
        existing = c.execute(
            "SELECT appearance_count, last_seen FROM story_history WHERE title_hash=?",
            (title_hash,),
        ).fetchone()

        if existing:
            if existing["last_seen"] < today:
                count = existing["appearance_count"] + 1
                c.execute(
                    "UPDATE story_history SET last_seen=?, appearance_count=? WHERE title_hash=?",
                    (today, count, title_hash),
                )
            else:
                # Already counted today — return the existing count unchanged.
                count = existing["appearance_count"]
        else:
            count = 1
            c.execute(
                """INSERT INTO story_history
                   (title_hash, title, category, first_seen, last_seen, appearance_count)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (title_hash, title[:255], category, today, today),
            )
        c.commit()
    return count


def get_trending_stories(days: int = 7, limit: int = 30) -> list[dict]:
    """
    Recurring stories from the last `days` days, most-repeated first.
    Only stories that appeared more than once (appearance_count >= 2) are
    returned — single-day stories aren't a weekly trend. Powers /digest.
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT title, category, appearance_count, first_seen, last_seen
            FROM story_history
            WHERE last_seen >= ? AND appearance_count >= 2
            ORDER BY appearance_count DESC, last_seen DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_story_count(title_hash: str) -> int:
    with _conn() as c:
        row = c.execute(
            "SELECT appearance_count FROM story_history WHERE title_hash=?",
            (title_hash,),
        ).fetchone()
    return row["appearance_count"] if row else 0


def purge_old_stories(days: int = 14) -> None:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with _conn() as c:
        deleted = c.execute(
            "DELETE FROM story_history WHERE last_seen < ?", (cutoff,)
        ).rowcount
        c.commit()
    if deleted:
        logger.info("Purged %d old story history record(s)", deleted)
