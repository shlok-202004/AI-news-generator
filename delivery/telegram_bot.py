import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_MAX_MESSAGE_LEN

logger = logging.getLogger(__name__)

# Delay between consecutive Telegram messages (seconds)
# Telegram allows ~30 msg/s to one chat — 1s is safe and avoids flood limits
_INTER_MESSAGE_DELAY = 1.0


# ── Message chunker ────────────────────────────────────────────────────────────

def _chunk_message(text: str, limit: int = TELEGRAM_MAX_MESSAGE_LEN) -> list[str]:
    """
    Split a message that exceeds Telegram's character limit.
    Splits on newlines to avoid cutting inside an HTML tag.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        if current_len + len(line) > limit and current_lines:
            chunks.append("".join(current_lines).rstrip())
            current_lines = [line]
            current_len = len(line)
        else:
            current_lines.append(line)
            current_len += len(line)

    if current_lines:
        chunks.append("".join(current_lines).rstrip())

    return chunks


# ── Single-message sender with retry ──────────────────────────────────────────

async def _send_message(bot: Bot, text: str, retries: int = 3) -> None:
    """
    Send one HTML message to TELEGRAM_CHAT_ID.
    Handles RetryAfter (flood control) transparently.
    """
    for attempt in range(retries):
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return

        except RetryAfter as exc:
            wait = exc.retry_after + 1
            logger.warning(
                "Telegram flood control: waiting %ds (attempt %d/%d)",
                wait, attempt + 1, retries,
            )
            await asyncio.sleep(wait)

        except TelegramError as exc:
            logger.error(
                "Telegram error on attempt %d/%d: %s",
                attempt + 1, retries, exc,
            )
            if attempt < retries - 1:
                await asyncio.sleep(3)

    logger.error("Failed to send message after %d attempts — skipping", retries)


# ── Header / footer builders ───────────────────────────────────────────────────

def _build_header() -> str:
    # IST = UTC+5:30
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    date_str = now.strftime("%A, %d %b %Y")
    return (
        f"<b>📰 Daily Intelligence Briefing</b>\n"
        f"<i>{date_str}</i>\n\n"
        f"Here's what matters today across tech, markets, geopolitics, and more 👇"
    )


def _build_footer() -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    time_str = now.strftime("%I:%M %p IST")
    return (
        f"<i>Generated at {time_str} · Powered by Claude</i>"
    )


# ── Main delivery function ─────────────────────────────────────────────────────

async def _deliver(sections: list[str], dry_run: bool = False) -> None:
    """
    Send briefing to Telegram.
    If dry_run=True, prints to stdout instead — useful for local testing.
    """
    all_messages: list[str] = [_build_header()]

    for section in sections:
        # Each section may itself need to be chunked
        all_messages.extend(_chunk_message(section))

    all_messages.append(_build_footer())

    if dry_run:
        print("\n" + "═" * 60)
        for msg in all_messages:
            print(msg)
            print("─" * 60)
        print("DRY RUN — nothing sent to Telegram")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    async with bot:
        logger.info("Sending %d message(s) to Telegram…", len(all_messages))
        for i, msg in enumerate(all_messages):
            await _send_message(bot, msg)
            if i < len(all_messages) - 1:
                await asyncio.sleep(_INTER_MESSAGE_DELAY)

    logger.info("Briefing delivered successfully ✓")


def send_briefing(sections: list[str], dry_run: bool = False) -> None:
    """
    Synchronous wrapper so callers don't need to manage an event loop.
    Safe to call from both sync scripts and APScheduler jobs.
    """
    asyncio.run(_deliver(sections, dry_run=dry_run))
