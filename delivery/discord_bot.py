"""
discord_bot.py — Discord bot with slash commands + daily scheduled briefing.

Run instead of scheduler.py when you want slash commands:
    python -m delivery.discord_bot

Slash commands:
    /news                   — full briefing (all categories)
    /news category:Tech     — single category briefing

Requires:
    DISCORD_BOT_TOKEN  — from discord.com/developers
    DISCORD_CHANNEL_ID — channel ID where the daily briefing is posted
"""

import asyncio
import logging
import os
import sys
import datetime

import discord
from discord import app_commands
from discord.ext import tasks

# ── Logging ────────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
for noisy in ("httpx", "httpcore", "discord.gateway", "discord.client", "trafilatura"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

from config import DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID
from delivery.discord_webhook import build_embeds
from main import build_sections

if not DISCORD_BOT_TOKEN:
    logger.error("DISCORD_BOT_TOKEN is not set in .env — bot cannot start")
    sys.exit(1)

if not DISCORD_CHANNEL_ID:
    logger.warning("DISCORD_CHANNEL_ID not set — scheduled daily briefing disabled")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

# ── Category choices for the slash command ─────────────────────────────────────
_CATEGORY_CHOICES = [
    app_commands.Choice(name="🖥️  Tech",           value="Tech"),
    app_commands.Choice(name="🤖  AI",              value="AI"),
    app_commands.Choice(name="📈  Stock Market",    value="Stock Market"),
    app_commands.Choice(name="🌍  Geopolitics",     value="Geopolitics"),
    app_commands.Choice(name="🇮🇳  India Politics", value="India Politics"),
    app_commands.Choice(name="🎬  Entertainment",   value="Entertainment"),
]


# ── Embed converter ────────────────────────────────────────────────────────────

def _to_discord_embeds(sections: list[str]) -> list[discord.Embed]:
    """Convert briefing sections → list[discord.Embed] for bot sending."""
    raw_embeds = build_embeds(sections)
    result: list[discord.Embed] = []

    for d in raw_embeds:
        embed = discord.Embed(
            title=d.get("title"),
            description=d.get("description"),
            color=d.get("color", 0x5865F2),
        )
        if "author" in d:
            embed.set_author(name=d["author"]["name"])
        if "timestamp" in d:
            try:
                embed.timestamp = datetime.datetime.fromisoformat(d["timestamp"])
            except (ValueError, TypeError):
                pass
        result.append(embed)

    return result


async def _send_embeds(
    target: discord.TextChannel | discord.Webhook,
    embeds: list[discord.Embed],
) -> None:
    """Send embeds in batches of 10 (Discord limit)."""
    for i in range(0, len(embeds), 10):
        await target.send(embeds=embeds[i : i + 10])


# ── Bot setup ──────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)


# ── Slash command: /news ───────────────────────────────────────────────────────

@tree.command(name="news", description="Get the latest AI-curated news briefing")
@app_commands.describe(category="Leave blank for all categories")
@app_commands.choices(category=_CATEGORY_CHOICES)
async def news_command(
    interaction: discord.Interaction,
    category: app_commands.Choice[str] | None = None,
) -> None:
    cat_value = category.value if category else None
    cat_label = category.name  if category else "all categories"

    await interaction.response.defer(thinking=True)
    logger.info("/news called by %s — category: %s", interaction.user, cat_label)

    try:
        sections = await asyncio.to_thread(build_sections, cat_value)
        embeds   = _to_discord_embeds(sections)
        # Send first batch as followup, rest as separate messages
        first_batch = embeds[:10]
        await interaction.followup.send(embeds=first_batch)
        for i in range(10, len(embeds), 10):
            await interaction.channel.send(embeds=embeds[i : i + 10])

        logger.info("/news delivered %d embed(s) for %s", len(embeds), cat_label)

    except ValueError as exc:
        await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
    except Exception as exc:
        logger.exception("/news command failed: %s", exc)
        await interaction.followup.send(
            "❌ Pipeline failed — check logs for details.", ephemeral=True
        )


# ── Daily scheduled briefing ───────────────────────────────────────────────────

@tasks.loop(time=datetime.time(hour=8, minute=0, tzinfo=IST))
async def daily_briefing() -> None:
    if not DISCORD_CHANNEL_ID:
        return

    channel = client.get_channel(int(DISCORD_CHANNEL_ID))
    if not channel:
        logger.error("Daily briefing: channel %s not found", DISCORD_CHANNEL_ID)
        return

    logger.info("Running scheduled daily briefing…")
    try:
        from main import run_pipeline
        # run_pipeline delivers via webhook AND marks articles as seen
        await asyncio.to_thread(run_pipeline, False)
        logger.info("Scheduled briefing delivered ✓")
    except Exception as exc:
        logger.exception("Scheduled briefing failed: %s", exc)
        await channel.send("❌ Daily briefing pipeline failed — check logs.")


# ── Bot events ─────────────────────────────────────────────────────────────────

@client.event
async def on_ready() -> None:
    await tree.sync()
    daily_briefing.start()
    logger.info(
        "Bot ready as %s — slash commands synced, daily briefing at 08:00 IST",
        client.user,
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN, log_handler=None)
