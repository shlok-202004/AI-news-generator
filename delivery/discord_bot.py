"""
discord_bot.py — Discord bot with slash commands + daily scheduled briefing.

Commands:
    /news [category]       — full or category briefing
    /summary topic:X       — 48-hour deep dive on any topic
    /subscribe category:X  — subscribe to daily DMs for a category
    /unsubscribe category:X
    /mysubscriptions       — view your active subscriptions
    /stats                 — reaction engagement leaderboard
    /digest                — weekly recap of recurring/trending stories
"""

import asyncio
import datetime
import logging
import os
import re
import sys

import discord
from discord import app_commands
from discord.ext import tasks

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

from config import DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, DISCORD_GUILD_ID, CATEGORIES
from delivery.discord_webhook import build_embeds
from ai.summarizer import CATEGORY_EMOJIS
from main import build_sections, run_pipeline
from db.store import (
    init_tables,
    subscribe, unsubscribe, get_subscriptions, get_all_subscriptions,
    record_message, record_reaction, get_reaction_stats,
    get_trending_stories,
)

if not DISCORD_BOT_TOKEN:
    logger.error("DISCORD_BOT_TOKEN is not set — bot cannot start")
    sys.exit(1)

init_tables()

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

_CATEGORY_CHOICES = [
    app_commands.Choice(name="🖥️  Tech",            value="Tech"),
    app_commands.Choice(name="🤖  AI",               value="AI"),
    app_commands.Choice(name="📈  Stock Market",     value="Stock Market"),
    app_commands.Choice(name="🌍  Geopolitics",      value="Geopolitics"),
    app_commands.Choice(name="🇮🇳  India Politics",  value="India Politics"),
    app_commands.Choice(name="🎬  Entertainment",    value="Entertainment"),
]

_SECTION_RE = re.compile(r"\[SECTION:\s*(.+?)\]")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dict_to_embed(d: dict) -> discord.Embed:
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
    return embed


def _to_discord_embeds(sections: list[str]) -> list[discord.Embed]:
    return [_dict_to_embed(d) for d in build_embeds(sections)]


def _filter_sections(sections: list[str], categories: list[str]) -> list[str]:
    """Return only sections whose category matches the user's subscriptions."""
    result = []
    for s in sections:
        m = _SECTION_RE.search(s)
        if m and any(cat.lower() in m.group(1).lower() for cat in categories):
            result.append(s)
    return result


async def _send_with_reactions(
    channel: discord.TextChannel, sections: list[str]
) -> None:
    """Send each category embed as its own message and add 👍👎 reactions."""
    raw_embeds = build_embeds(sections)
    for d in raw_embeds:
        embed = _dict_to_embed(d)
        msg   = await channel.send(embed=embed)
        if "author" in d:                          # category embed only
            category = d["author"]["name"]
            record_message(str(msg.id), category)
            try:
                await msg.add_reaction("👍")
                await msg.add_reaction("👎")
            except discord.HTTPException:
                pass


# ── Bot setup ──────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)


# ── /news ──────────────────────────────────────────────────────────────────────

@tree.command(name="news", description="Get the latest AI-curated news briefing")
@app_commands.describe(category="Leave blank for all categories")
@app_commands.choices(category=_CATEGORY_CHOICES)
async def cmd_news(
    interaction: discord.Interaction,
    category: app_commands.Choice[str] | None = None,
) -> None:
    cat_val   = category.value if category else None
    cat_label = category.name  if category else "all categories"
    await interaction.response.defer(thinking=True)
    logger.info("/news by %s — %s", interaction.user, cat_label)
    try:
        sections = await asyncio.to_thread(build_sections, cat_val)
        # Acknowledge the interaction so Discord doesn't timeout the deferred response
        await interaction.followup.send(
            f"📰 **{cat_label}** briefing incoming…", ephemeral=True
        )
        # Post to the channel with 👍/👎 reactions so /stats can track engagement
        await _send_with_reactions(interaction.channel, sections)
    except ValueError as exc:
        await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
    except Exception as exc:
        logger.exception("/news failed: %s", exc)
        await interaction.followup.send("❌ Pipeline failed — check logs.", ephemeral=True)


# ── /summary ───────────────────────────────────────────────────────────────────

@tree.command(name="summary", description="Deep-dive on any topic from the last 48 hours")
@app_commands.describe(topic="e.g. 'OpenAI', 'India budget', 'Ukraine'")
async def cmd_summary(interaction: discord.Interaction, topic: str) -> None:
    await interaction.response.defer(thinking=True)
    logger.info("/summary by %s — topic: %s", interaction.user, topic)
    try:
        from fetchers.gnews_fetcher import fetch_topic
        from fetchers.scraper import enrich_articles
        from ai.summarizer import generate_deep_dive

        articles = await asyncio.to_thread(fetch_topic, topic, 10, 48)
        if not articles:
            await interaction.followup.send(
                f"⚠️ No news found for **{topic}** in the last 48 hours.", ephemeral=True
            )
            return

        enriched = await asyncio.to_thread(enrich_articles, {"_topic": articles})
        content  = await asyncio.to_thread(generate_deep_dive, topic, enriched["_topic"])

        embed = discord.Embed(
            title=f"🔍  Deep Dive: {topic}",
            description=content,
            color=0x5865F2,
            timestamp=datetime.datetime.now(IST),
        )
        embed.set_footer(text=f"Based on {len(articles)} articles · last 48 hours")
        await interaction.followup.send(embed=embed)
    except Exception as exc:
        logger.exception("/summary failed: %s", exc)
        await interaction.followup.send("❌ Summary failed — check logs.", ephemeral=True)


# ── /subscribe ─────────────────────────────────────────────────────────────────

@tree.command(name="subscribe", description="Subscribe to daily DMs for a news category")
@app_commands.describe(category="Category to subscribe to")
@app_commands.choices(category=_CATEGORY_CHOICES)
async def cmd_subscribe(
    interaction: discord.Interaction,
    category: app_commands.Choice[str],
) -> None:
    added = subscribe(str(interaction.user.id), category.value)
    if added:
        await interaction.response.send_message(
            f"✅ Subscribed to **{category.name}** — you'll get a daily DM at 08:00 IST.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"ℹ️ You're already subscribed to **{category.name}**.", ephemeral=True
        )


# ── /unsubscribe ───────────────────────────────────────────────────────────────

@tree.command(name="unsubscribe", description="Unsubscribe from daily DMs for a category")
@app_commands.choices(category=_CATEGORY_CHOICES)
async def cmd_unsubscribe(
    interaction: discord.Interaction,
    category: app_commands.Choice[str],
) -> None:
    removed = unsubscribe(str(interaction.user.id), category.value)
    if removed:
        await interaction.response.send_message(
            f"🗑️ Unsubscribed from **{category.name}**.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"ℹ️ You weren't subscribed to **{category.name}**.", ephemeral=True
        )


# ── /mysubscriptions ───────────────────────────────────────────────────────────

@tree.command(name="mysubscriptions", description="See your active category subscriptions")
async def cmd_mysubs(interaction: discord.Interaction) -> None:
    cats = get_subscriptions(str(interaction.user.id))
    if cats:
        lines = "\n".join(f"• {c}" for c in cats)
        await interaction.response.send_message(
            f"📋 **Your subscriptions:**\n{lines}\n\nYou'll receive a DM daily at 08:00 IST.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "You have no active subscriptions. Use `/subscribe` to add one.", ephemeral=True
        )


# ── /stats ─────────────────────────────────────────────────────────────────────

@tree.command(name="stats", description="See which news categories get the most reactions")
async def cmd_stats(interaction: discord.Interaction) -> None:
    rows = get_reaction_stats()
    if not rows:
        await interaction.response.send_message(
            "No reaction data yet — reactions are collected from daily briefings.", ephemeral=True
        )
        return

    lines = ["**📊 Category Engagement (all-time)**\n"]
    for r in rows:
        total = r["thumbs_up"] + r["thumbs_down"]
        pct   = int(r["thumbs_up"] / total * 100) if total else 0
        lines.append(f"**{r['category']}** — 👍 {r['thumbs_up']}  👎 {r['thumbs_down']}  ({pct}% positive)")

    embed = discord.Embed(
        title="📊 News Category Stats",
        description="\n".join(lines),
        color=0x5865F2,
    )
    await interaction.response.send_message(embed=embed)


# ── /digest ────────────────────────────────────────────────────────────────────

@tree.command(name="digest", description="Weekly recap of stories that kept trending")
async def cmd_digest(interaction: discord.Interaction) -> None:
    stories = get_trending_stories(days=7)
    if not stories:
        await interaction.response.send_message(
            "No recurring stories this week yet — the digest builds up as daily "
            "briefings track which stories keep returning.",
            ephemeral=True,
        )
        return

    # Group by category, preserving config order
    by_category: dict[str, list[dict]] = {}
    for s in stories:
        by_category.setdefault(s["category"], []).append(s)

    lines: list[str] = []
    for category in CATEGORIES:
        bucket = by_category.get(category)
        if not bucket:
            continue
        emoji = CATEGORY_EMOJIS.get(category, "📰")
        lines.append(f"\n{emoji} **{category}**")
        for s in bucket:
            lines.append(f"• {s['title']}  `×{s['appearance_count']}`")

    description = ("Stories that kept coming back over the last 7 days "
                  "(`×N` = days seen).\n" + "\n".join(lines))
    if len(description) > 4096:
        description = description[:4093] + "…"

    embed = discord.Embed(
        title="🔁 Weekly Digest",
        description=description,
        color=0x5865F2,
        timestamp=datetime.datetime.now(IST),
    )
    await interaction.response.send_message(embed=embed)


# ── Reaction tracking ──────────────────────────────────────────────────────────

@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    if payload.user_id == client.user.id:
        return  # ignore bot's own reactions
    emoji = str(payload.emoji)
    if emoji not in ("👍", "👎"):
        return
    category = record_reaction(str(payload.message_id), emoji)
    if category:
        logger.debug("Reaction %s on %s (%s)", emoji, payload.message_id, category)


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
        # Run pipeline (fetch → scrape → trend → AI → mark seen).
        # deliver=False: the bot is the sole poster (with reactions) — avoids
        # the webhook posting a duplicate copy to the same channel.
        sections = await asyncio.to_thread(run_pipeline, False, False)

        # Send with per-category reactions via bot
        await _send_with_reactions(channel, sections)

        # Personalized DMs
        subs = get_all_subscriptions()
        for user_id, categories in subs.items():
            user_sections = _filter_sections(sections, categories)
            if not user_sections:
                continue
            try:
                user = await client.fetch_user(int(user_id))
                dm   = await user.create_dm()
                header = discord.Embed(
                    title="📰 Your Personalized Daily Brief",
                    description="Categories: " + ", ".join(f"**{c}**" for c in categories),
                    color=0x5865F2,
                    timestamp=datetime.datetime.now(IST),
                )
                await dm.send(embed=header)
                for embed in _to_discord_embeds(user_sections):
                    await dm.send(embed=embed)
            except Exception as exc:
                logger.warning("Could not DM user %s: %s", user_id, exc)

        logger.info("Daily briefing + DMs delivered ✓")
    except Exception as exc:
        logger.exception("Daily briefing failed: %s", exc)
        await channel.send("❌ Daily briefing pipeline failed — check logs.")


# ── Bot events ─────────────────────────────────────────────────────────────────

@client.event
async def on_ready() -> None:
    if DISCORD_GUILD_ID:
        guild = discord.Object(id=int(DISCORD_GUILD_ID))
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        logger.info("Slash commands synced to guild %s (instant)", DISCORD_GUILD_ID)
    else:
        await tree.sync()
        logger.info("Slash commands synced globally (may take up to 1 hour)")

    daily_briefing.start()
    logger.info("Bot ready as %s — daily briefing at 08:00 IST", client.user)


if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN, log_handler=None)
