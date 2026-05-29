import re
import logging
from datetime import datetime, timezone, timedelta

import httpx

from config import DISCORD_WEBHOOK_URL, AI_PROVIDER

logger = logging.getLogger(__name__)

_DISCORD_DESC_LIMIT  = 4096   # max chars in an embed description
_DISCORD_TITLE_LIMIT = 256    # max chars in an embed title
_DISCORD_TOTAL_LIMIT = 6000   # max chars across ALL embeds in one message
_MAX_EMBEDS_PER_MSG  = 10     # max embeds Discord accepts per message

_SECTION_RE = re.compile(r"^\[SECTION:\s*(.+?)\]", re.MULTILINE)
_BIGPIC_RE  = re.compile(r"^\[BIGPIC:\s*(.+?)\]",  re.MULTILINE)

# Unique left-border color per category
_CATEGORY_COLORS: dict[str, int] = {
    # Original
    "tech":                  0x00B4D8,  # cyan
    "ai":                    0x9B59B6,  # purple
    "stock market":          0x2ECC71,  # green
    "geopolitics":           0xE74C3C,  # red
    "india politics":        0xF39C12,  # orange
    "entertainment":         0xE91E8C,  # pink
    # New categories
    "startups & vc":         0xFF6B35,  # startup orange
    "science & space":       0x1ABC9C,  # teal
    "cybersecurity":         0xE74C3C,  # red (threats)
    "automotive & ev":       0x27AE60,  # green (electric)
    "gaming":                0x8E44AD,  # violet
    "health & medicine":     0x3498DB,  # blue
    "us politics":           0xC0392B,  # dark red
    "uk politics":           0x2980B9,  # royal blue
    "middle east":           0xE67E22,  # sand orange
    "china & asia":          0xC0392B,  # red
    "europe":                0x2980B9,  # EU blue
    "defence & military":    0x7F8C8D,  # steel grey
    "africa":                0xF39C12,  # gold
    "latin america":         0x16A085,  # teal green
    "sports":                0x27AE60,  # green
    "business & leadership": 0x2C3E50,  # dark navy
    "climate & environment": 0x2ECC71,  # leaf green
    "media & journalism":    0x95A5A6,  # silver
    "education & edtech":    0xF1C40F,  # yellow
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
            embed["title"] = f"💡 {big_picture}"[:_DISCORD_TITLE_LIMIT]
        if stories:
            embed["description"] = stories

        embeds.append(embed)

    # ── Footer embed ──────────────────────────────────────────────────────────
    provider = "Google Gemini" if AI_PROVIDER.lower() == "gemini" else "OpenRouter AI"
    embeds.append({
        "description": (
            f"-# 🤖 Powered by {provider}  ·  📡 Sources via GNews + RSS  ·  "
            f"📅 {date_str}"
        ),
        "color": 0x2B2D31,
    })

    return embeds


def _embed_len(embed: dict) -> int:
    """Count the characters Discord tallies against the 6000-per-message limit."""
    total = len(embed.get("title", "")) + len(embed.get("description", ""))
    author = embed.get("author")
    if author:
        total += len(author.get("name", ""))
    return total


def _batch_embeds(embeds: list[dict]) -> list[list[dict]]:
    """
    Split embeds into Discord-legal batches: each message holds at most
    10 embeds AND at most 6000 characters across them. With 25 categories a
    naive 10-per-message split blows past 6000 chars and the send 400s.
    """
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_len = 0
    for embed in embeds:
        elen = _embed_len(embed)
        if current and (
            len(current) >= _MAX_EMBEDS_PER_MSG
            or current_len + elen > _DISCORD_TOTAL_LIMIT
        ):
            batches.append(current)
            current, current_len = [], 0
        current.append(embed)
        current_len += elen
    if current:
        batches.append(current)
    return batches


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

    # Discord limits each message to 10 embeds AND 6000 total characters.
    batches = _batch_embeds(embeds)
    for idx, batch in enumerate(batches, 1):
        _send_payload({"embeds": batch})
        logger.info("Sent embed batch %d/%d", idx, len(batches))

    logger.info("Briefing delivered to Discord ✓")
