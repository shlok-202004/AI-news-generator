import re
import logging
from datetime import datetime, timezone, timedelta

import httpx

from config import DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)

_DISCORD_DESC_LIMIT = 4096

_SECTION_RE = re.compile(r"^\[SECTION:\s*(.+?)\]", re.MULTILINE)
_BIGPIC_RE  = re.compile(r"^\[BIGPIC:\s*(.+?)\]",  re.MULTILINE)

# Unique left-border color per category
_CATEGORY_COLORS: dict[str, int] = {
    "tech":           0x00B4D8,  # cyan
    "ai":             0x9B59B6,  # purple
    "stock market":   0x2ECC71,  # green
    "geopolitics":    0xE74C3C,  # red
    "india politics": 0xF39C12,  # orange
    "entertainment":  0xE91E8C,  # pink
}
_DEFAULT_COLOR = 0x5865F2  # Discord blurple


def _category_color(header: str) -> int:
    lower = header.lower()
    for key, color in _CATEGORY_COLORS.items():
        if key in lower:
            return color
    return _DEFAULT_COLOR


def _parse_section(raw: str) -> tuple[str, str, str]:
    """Return (header, big_picture, stories_body) for one section block."""
    sm = _SECTION_RE.search(raw)
    header = sm.group(1).strip() if sm else "📰 News"

    bm = _BIGPIC_RE.search(raw)
    big_picture = bm.group(1).strip() if bm else ""

    # Remove the marker lines; keep everything else (the 🔹 stories)
    body = raw
    if sm:
        body = body.replace(sm.group(0), "", 1)
    if bm:
        body = body.replace(bm.group(0), "", 1)

    stories = body.strip()
    return header, big_picture, stories


def build_embeds(sections: list[str]) -> list[dict]:
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    date_str = now.strftime("%A, %d %B %Y")
    time_str = now.strftime("%I:%M %p IST")

    embeds: list[dict] = []

    # ── Header embed ──────────────────────────────────────────────────────────
    embeds.append({
        "title": "📰  Daily Intelligence Brief",
        "description": (
            f"**{date_str}**\n"
            f"-# Curated across **{len(sections)} categories** — facts only, no filler.\n\n"
            f"*Delivered at {time_str}*"
        ),
        "color": 0x5865F2,
        "timestamp": now.isoformat(),
    })

    # ── One embed per category ─────────────────────────────────────────────────
    for section in sections:
        header, big_picture, stories = _parse_section(section)
        color = _category_color(header)

        if len(stories) > _DISCORD_DESC_LIMIT:
            stories = stories[: _DISCORD_DESC_LIMIT - 3] + "…"

        embed: dict = {
            "author": {"name": header},
            "color":  color,
        }
        if big_picture:
            # Big picture sits as the embed title — large, bold, immediately visible
            embed["title"] = f"💡 {big_picture}"
        if stories:
            embed["description"] = stories

        embeds.append(embed)

    # ── Footer embed ──────────────────────────────────────────────────────────
    embeds.append({
        "description": (
            "-# 🤖 Powered by OpenRouter AI  ·  📡 Sources via GNews  ·  "
            f"📅 {date_str}"
        ),
        "color": 0x2B2D31,
    })

    return embeds


def _send_payload(payload: dict) -> None:
    resp = httpx.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()


def send_briefing(sections: list[str], dry_run: bool = False) -> None:
    """
    Send the briefing to Discord via webhook.
    Discord allows max 10 embeds per message — we batch accordingly.
    If dry_run=True, prints to stdout instead.
    """
    embeds = build_embeds(sections)

    if dry_run:
        print("\n" + "═" * 64)
        for embed in embeds:
            if "author" in embed:
                print(f"\n  ▌ {embed['author']['name']}")
            if embed.get("title"):
                print(f"  {embed['title']}")
            if embed.get("description"):
                print(embed["description"])
            print("─" * 64)
        print("\nDRY RUN — nothing sent to Discord")
        return

    # Discord limit: 10 embeds per request
    _BATCH = 10
    for i in range(0, len(embeds), _BATCH):
        batch = embeds[i : i + _BATCH]
        _send_payload({"embeds": batch})
        logger.info("Sent embed batch %d/%d", i // _BATCH + 1, -(-len(embeds) // _BATCH))

    logger.info("Briefing delivered to Discord ✓")
