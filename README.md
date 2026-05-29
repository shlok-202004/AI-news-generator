# AI News Generator

A daily news briefing pipeline that fetches, deduplicates, ranks, and summarizes news across **25 categories** using AI — delivered to Discord via bot and webhook.

## Features

- **Multi-source fetching** — GNews API + 60+ RSS feeds across 25 categories, both fetched in parallel
- **Smart deduplication** — exact URL fingerprinting + Jaccard fuzzy title matching
- **Quality-based ranking** — source tier, recency, description quality, and clickbait penalties
- **Full-text scraping** — trafilatura enriches articles in parallel before sending to AI
- **Trend detection** — tracks recurring stories across days (`🔥 TRENDING`, `📌 UPDATE` tags)
- **AI briefing generation** — OpenRouter (Llama, etc.) or Gemini; retries automatically on malformed output
- **GNews quota fallback** — auto-switches to RSS-only mode on quota exhaustion; self-resets after 24 h
- **Discord bot** — slash commands with autocomplete, per-category reactions, personalized DMs, weekly digest
- **Scheduled delivery** — daily briefing at 08:00 IST via built-in bot scheduler

## Categories (25)

| | Category | Key Sources |
|---|---|---|
| 🖥️ | Tech | TechCrunch, Wired, Ars Technica, The Verge |
| 🤖 | AI | VentureBeat, MIT Technology Review |
| 📈 | Stock Market | Yahoo Finance, CNBC |
| 🌍 | Geopolitics | BBC, The Guardian, Al Jazeera |
| 🇮🇳 | India Politics | The Hindu, Indian Express |
| 🎬 | Entertainment | Variety, Deadline |
| 🚀 | Startups & VC | TechCrunch Startups, TechCrunch Venture, Crunchbase |
| 🔬 | Science & Space | NASA, Science Daily, Ars Technica Science, Space.com |
| 🔐 | Cybersecurity | The Hacker News, Bleeping Computer, Krebs on Security |
| 🚗 | Automotive & EV | Electrek, InsideEVs |
| 🎮 | Gaming | IGN, Polygon, Kotaku |
| 🏥 | Health & Medicine | STAT News, Science Daily Health, Healthline |
| 🇺🇸 | US Politics | NPR Politics, The Hill |
| 🇬🇧 | UK Politics | BBC Politics, The Guardian Politics |
| 🕌 | Middle East | BBC Middle East, The Guardian Middle East |
| 🏯 | China & Asia | BBC Asia, Nikkei Asia |
| 🇪🇺 | Europe | BBC Europe, Politico Europe |
| ⚔️ | Defence & Military | Defense One, Breaking Defense |
| 🌍 | Africa | BBC Africa, The Guardian Africa |
| 🌎 | Latin America | BBC Latin America, The Guardian Americas |
| ⚽ | Sports | BBC Sport, Sky Sports |
| 💼 | Business & Leadership | Fortune, Business Insider, Fast Company |
| 🌱 | Climate & Environment | The Guardian Environment, Inside Climate News |
| 📰 | Media & Journalism | Nieman Lab, Digiday |
| 🎓 | Education & EdTech | Campus Technology |

## Discord Slash Commands

| Command | Description |
|---|---|
| `/news [category]` | Full briefing or single category — shows all fetched articles, with 👍/👎 reactions |
| `/summary topic:X` | Deep-dive on any topic from the last 48 hours |
| `/digest` | Weekly recap of stories that kept reappearing (`×N` = days seen) |
| `/subscribe category:X` | Subscribe to daily DMs for a category |
| `/unsubscribe category:X` | Unsubscribe from a category |
| `/mysubscriptions` | View your active subscriptions |
| `/stats` | Reaction leaderboard + live GNews API quota status |

> All category commands use **autocomplete** — start typing and Discord suggests matching categories from all 25.

## Project Structure

```
├── main.py                  # Pipeline entrypoint (fetch → dedup → AI → deliver)
├── scheduler.py             # APScheduler: runs pipeline daily at 08:00 IST
├── config.py                # All config: 25 categories, API keys, limits
│
├── fetchers/
│   ├── gnews_fetcher.py     # GNews API client, quota tracking + fallback
│   ├── rss_fetcher.py       # Parallel RSS/Atom feed fetcher (8 workers)
│   └── scraper.py           # Full-text scraping via trafilatura (6 workers)
│
├── processor/
│   ├── deduplicator.py      # URL hash dedup + Jaccard fuzzy title dedup
│   ├── filter.py            # Scoring and ranking (source tier, recency, quality)
│   └── trend_tracker.py     # Story history comparison, trending/update tagging
│
├── ai/
│   └── summarizer.py        # OpenRouter / Gemini briefing generation with format retry
│
├── delivery/
│   ├── discord_webhook.py   # Embed builder + webhook sender (25 category colors)
│   └── discord_bot.py       # discord.py bot: slash commands, autocomplete, reactions, DMs
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
| `GNEWS_API_KEY` | Yes | [gnews.io](https://gnews.io) free tier: 100 req/day |
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

**Scheduled daily briefing at 08:00 IST (webhook only, no bot):**
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
GNews API ──┐  (parallel, 25 categories)
            ├──► Deduplicate ──► Rank & Score ──► Scrape full text ──► Tag trends ──► AI ──► Discord
RSS feeds ──┘  (parallel, 60+ feeds)
```

1. **Fetch** — GNews API + RSS for all 25 categories in parallel; auto-falls back to RSS-only if GNews quota is exhausted
2. **Deduplicate** — drop already-seen URLs (SQLite, 3-day TTL) + Jaccard fuzzy title dedup within batch
3. **Rank** — score by source tier (30/20/10/5 pts), recency (linear 40pt decay over 24 h), description length, title quality; penalise clickbait
4. **Scrape** — fetch full article text in parallel (6 workers, 8 s timeout, trafilatura); falls back to RSS description on failure
5. **Trend-tag** — compare against 14-day story history; prepend `🔥 TRENDING — Day N` or `📌 UPDATE`
6. **AI** — send all ranked articles per category to OpenRouter/Gemini; retries up to 3× on malformed output; generates Discord-formatted briefing
7. **Deliver** — post embeds with unique per-category colors; mark articles as seen only after successful delivery

## GNews Quota & Fallback

The free GNews tier allows **100 requests/day**. With 25 categories each using 1 request, each full pipeline run costs 25 requests (~4 runs/day available).

When the quota is exhausted (HTTP 429/403):
- The pipeline automatically switches to **RSS-only mode** for the remainder of the day
- No GNews requests are made until the 24-hour window resets
- `/stats` always shows the current quota status (`✅ available` or `⚠️ exhausted — resets at HH:MM UTC`)
- RSS alone provides 200–400 articles across all 25 categories per run

## Requirements

- Python 3.10+
- See `requirements.txt` for pinned package versions
