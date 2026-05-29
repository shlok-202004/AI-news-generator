# AI News Generator

A daily news briefing pipeline that fetches, deduplicates, ranks, and summarizes news across six categories using AI — delivered to Discord via bot and webhook.

## Features

- **Multi-source fetching** — GNews API + 15+ RSS feeds across 6 categories
- **Smart deduplication** — exact URL fingerprinting + Jaccard fuzzy title matching
- **Quality-based ranking** — source tier, recency, description quality, and clickbait penalties
- **Full-text scraping** — trafilatura enriches articles before sending to AI
- **Trend detection** — tracks recurring stories across days (`🔥 TRENDING`, `📌 UPDATE` tags)
- **AI briefing generation** — OpenRouter (Llama, etc.) or Gemini; structured Discord-formatted output
- **Discord bot** — slash commands, per-category reactions, personalized DMs, weekly digest
- **Dual delivery** — webhook for the scheduled briefing, bot for interactive commands

## Categories

| Category | Sources |
|---|---|
| 🖥️ Tech | TechCrunch, Wired, Ars Technica, The Verge + GNews |
| 🤖 AI | VentureBeat, MIT Technology Review + GNews |
| 📈 Stock Market | Yahoo Finance, CNBC + GNews |
| 🌍 Geopolitics | BBC, The Guardian, Al Jazeera + GNews |
| 🇮🇳 India Politics | The Hindu, Indian Express + GNews |
| 🎬 Entertainment | Variety, Deadline + GNews |

## Discord Slash Commands

| Command | Description |
|---|---|
| `/news [category]` | Full or single-category briefing with 👍/👎 reactions |
| `/summary topic:X` | Deep-dive on any topic from the last 48 hours |
| `/digest` | Weekly recap of stories that kept trending |
| `/subscribe category:X` | Subscribe to daily DMs for a category |
| `/unsubscribe category:X` | Unsubscribe from a category |
| `/mysubscriptions` | View your active subscriptions |
| `/stats` | Reaction engagement leaderboard by category |

## Project Structure

```
├── main.py                  # Pipeline entrypoint (fetch → dedup → AI → deliver)
├── scheduler.py             # APScheduler: runs pipeline daily at 08:00 IST
├── config.py                # All configuration: categories, API keys, limits
│
├── fetchers/
│   ├── gnews_fetcher.py     # GNews API client + Article dataclass
│   ├── rss_fetcher.py       # Parallel RSS/Atom feed fetcher
│   └── scraper.py           # Full-text scraping via trafilatura (parallel)
│
├── processor/
│   ├── deduplicator.py      # URL hash dedup + Jaccard fuzzy title dedup
│   ├── filter.py            # Scoring and ranking (source tier, recency, quality)
│   └── trend_tracker.py     # Story history comparison, trending/update tagging
│
├── ai/
│   └── summarizer.py        # OpenRouter / Gemini briefing generation
│
├── delivery/
│   ├── discord_webhook.py   # Embed builder + webhook sender
│   └── discord_bot.py       # discord.py bot: slash commands, reactions, DMs
│
└── db/
    └── store.py             # SQLite: seen articles, subscriptions, reactions, story history
```

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/shlok-202004/AI-news-generator.git
cd AI-news-generator
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `GNEWS_API_KEY` | Yes | [gnews.io](https://gnews.io) free tier (100 req/day) |
| `DISCORD_WEBHOOK_URL` | Yes | Webhook URL for the delivery channel |
| `AI_PROVIDER` | Yes | `openrouter` or `gemini` |
| `OPENROUTER_API_KEY` | If using OpenRouter | [openrouter.ai](https://openrouter.ai) |
| `OPENROUTER_MODEL` | No | Default: `meta-llama/llama-3.3-70b-instruct` |
| `GEMINI_API_KEY` | If using Gemini | Google AI Studio key |
| `GEMINI_MODEL` | No | Default: `gemini-2.5-flash` |
| `DISCORD_BOT_TOKEN` | For slash commands | Discord developer portal |
| `DISCORD_CHANNEL_ID` | For scheduled bot posts | Channel ID (numeric) |
| `DISCORD_GUILD_ID` | Recommended | Server ID for instant slash command sync |

### 3. Run

**Manual one-off briefing:**
```bash
python main.py
```

**Dry run (prints to stdout, no Discord):**
```bash
python main.py --dry-run
```

**Scheduled daily briefing at 08:00 IST (no bot):**
```bash
python scheduler.py
```

**Full bot with slash commands + scheduled briefing:**
```bash
python delivery/discord_bot.py
```

> When running the bot, skip `scheduler.py` — the bot handles the 08:00 IST schedule internally.

## Pipeline

```
GNews API ──┐
            ├──► Deduplicate ──► Rank & Score ──► Scrape full text ──► Tag trends ──► AI ──► Discord
RSS feeds ──┘
```

1. **Fetch** — GNews API + RSS for all 6 categories (parallel)
2. **Deduplicate** — drop already-seen URLs (SQLite TTL 3 days) + fuzzy title dedup within batch
3. **Rank** — score by source tier (30/20/10/5), recency (linear 40pt decay over 24h), description length, title quality; drop clickbait
4. **Scrape** — fetch full article text in parallel (6 workers, 8s timeout, trafilatura)
5. **Trend-tag** — compare against 14-day story history; prepend `🔥 TRENDING` / `📌 UPDATE`
6. **AI** — send top 10 articles per category to OpenRouter/Gemini; generate Discord-formatted briefing
7. **Deliver** — post embeds to Discord; mark articles as seen only after successful delivery

## Requirements

- Python 3.10+
- See `requirements.txt` for packages
