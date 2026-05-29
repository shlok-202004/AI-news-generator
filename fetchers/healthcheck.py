"""
fetchers/healthcheck.py — Probe every configured RSS feed and report its health.

Run as a script:
    python -m fetchers.healthcheck

Or call check_all_feeds() for structured results (used by the /feedhealth command).

Each feed is classified:
    ok    — reachable and carries entries
    empty — reachable but zero entries (feed may be broken, or just quiet)
    error — unreachable / parse failure (DNS, HTTP 4xx/5xx, malformed XML)

Raw entry count and *fresh* count (within MAX_AGE_HOURS) are reported separately,
so a healthy-but-quiet feed isn't mistaken for a dead one.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.error import URLError

import feedparser

from config import CATEGORIES
from fetchers.rss_fetcher import _is_fresh, _parse_rss_dt

logger = logging.getLogger(__name__)

_WORKERS = 8


def _domain(url: str) -> str:
    parts = url.split("/")
    return parts[2] if len(parts) > 2 else url


def check_feed(feed_url: str, category: str) -> dict:
    """Probe one feed and return a health record."""
    record = {
        "category": category,
        "feed_url": feed_url,
        "domain": _domain(feed_url),
        "status": "ok",
        "entries": 0,
        "fresh": 0,
        "detail": "",
    }

    try:
        parsed = feedparser.parse(feed_url)
    except Exception as exc:  # feedparser rarely raises, but be safe
        record["status"] = "error"
        record["detail"] = str(exc)[:140]
        return record

    entries = parsed.entries or []
    record["entries"] = len(entries)
    record["fresh"] = sum(1 for e in entries if _is_fresh(_parse_rss_dt(e)))

    http_status = parsed.get("status")
    bozo_exc = parsed.get("bozo_exception") if parsed.get("bozo") else None

    if entries:
        record["status"] = "ok"
        record["detail"] = (parsed.feed.get("title") or "")[:140]
    elif isinstance(bozo_exc, URLError) or (http_status and http_status >= 400):
        record["status"] = "error"
        record["detail"] = (
            f"HTTP {http_status}" if (http_status and http_status >= 400)
            else str(bozo_exc)[:140]
        )
    else:
        record["status"] = "empty"
        record["detail"] = str(bozo_exc)[:140] if bozo_exc else "0 entries"

    return record


def check_all_feeds() -> list[dict]:
    """Probe every feed across all categories, in parallel."""
    tasks = [
        (feed_url, category)
        for category, cfg in CATEGORIES.items()
        for feed_url in cfg.get("rss_feeds", [])
    ]
    if not tasks:
        return []
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        return list(pool.map(lambda t: check_feed(*t), tasks))


def summarize(results: list[dict]) -> dict[str, int]:
    """Count feeds by status."""
    return {
        "total": len(results),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "empty": sum(1 for r in results if r["status"] == "empty"),
        "error": sum(1 for r in results if r["status"] == "error"),
    }


# ── CLI report ──────────────────────────────────────────────────────────────

_ICONS = {"ok": "✅", "empty": "⚠️", "error": "❌"}


def _print_report(results: list[dict]) -> None:
    by_category: dict[str, list[dict]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r)

    counts = summarize(results)
    print(f"\nRSS Feed Health — {counts['total']} feeds across {len(by_category)} categories\n")

    for category in CATEGORIES:  # config order for stable output
        rows = by_category.get(category)
        if not rows:
            continue
        print(category)
        for r in rows:
            icon = _ICONS[r["status"]]
            note = f"{r['fresh']} fresh" if r["status"] == "ok" else r["detail"]
            print(f"  {icon} {r['domain']:<34} {r['entries']:>3} entries  {note}")
        print()

    print(f"Summary: {counts['ok']} ok · {counts['empty']} empty · {counts['error']} error")

    problems = [r for r in results if r["status"] != "ok"]
    if problems:
        print("\nNeeds attention:")
        for r in problems:
            print(f"  {_ICONS[r['status']]} {r['category']} / {r['domain']} — {r['detail']}")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    logging.basicConfig(level=logging.WARNING)
    _print_report(check_all_feeds())
