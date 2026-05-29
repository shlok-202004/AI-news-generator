import os
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ────────────────────────────────────────────────────────────────
AI_PROVIDER           = os.getenv("AI_PROVIDER", "openrouter")
OPENROUTER_API_KEY    = os.getenv("OPENROUTER_API_KEY")
GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY")
GNEWS_API_KEY         = os.getenv("GNEWS_API_KEY")
DISCORD_WEBHOOK_URL   = os.getenv("DISCORD_WEBHOOK_URL")
DISCORD_BOT_TOKEN     = os.getenv("DISCORD_BOT_TOKEN")      # optional — only needed for slash commands
DISCORD_CHANNEL_ID    = os.getenv("DISCORD_CHANNEL_ID")     # channel where scheduled briefing is posted
DISCORD_GUILD_ID      = os.getenv("DISCORD_GUILD_ID")       # your server ID — enables instant slash command sync

# ── Sanity check at import time ────────────────────────────────────────────────
_REQUIRED = {
    "GNEWS_API_KEY":        GNEWS_API_KEY,
    "DISCORD_WEBHOOK_URL":  DISCORD_WEBHOOK_URL,
}

if AI_PROVIDER.lower() == "openrouter":
    _REQUIRED["OPENROUTER_API_KEY"] = OPENROUTER_API_KEY
elif AI_PROVIDER.lower() == "gemini":
    _REQUIRED["GEMINI_API_KEY"] = GEMINI_API_KEY

_MISSING = [k for k, v in _REQUIRED.items() if not v]
if _MISSING:
    raise EnvironmentError(f"Missing required env vars: {', '.join(_MISSING)}")


# ── Category definitions ───────────────────────────────────────────────────────
# Each category has:
#   gnews_query  → passed to GNews `q` param (simple keywords, AND/OR supported)
#   gnews_lang   → ISO 639-1 language code
#   rss_feeds    → list of RSS/Atom feed URLs (free, no key needed)
CATEGORIES: dict[str, dict] = {
    "Tech": {
        "gnews_query": "technology OR cybersecurity OR Apple OR Google OR Microsoft",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://techcrunch.com/feed/",
            "https://www.wired.com/feed/rss",
            "https://feeds.arstechnica.com/arstechnica/index",
            "https://www.theverge.com/rss/index.xml",
        ],
    },
    "AI": {
        "gnews_query": "artificial intelligence OR OpenAI OR LLM OR machine learning",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://venturebeat.com/category/ai/feed/",
            "https://www.technologyreview.com/feed/",
        ],
    },
    "Stock Market": {
        "gnews_query": "stock market OR NASDAQ OR S&P 500 OR Wall Street OR earnings",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
            "https://feeds.reuters.com/reuters/businessNews",
        ],
    },
    "Geopolitics": {
        "gnews_query": "geopolitics OR sanctions OR NATO OR diplomacy OR Ukraine",
        "gnews_lang": "en",
        "rss_feeds": [
            "http://feeds.bbci.co.uk/news/world/rss.xml",
            "https://feeds.reuters.com/Reuters/worldNews",
            "https://www.aljazeera.com/xml/rss/all.xml",
        ],
    },
    "India Politics": {
        "gnews_query": "India politics OR Modi OR BJP OR Indian parliament OR Indian election",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://www.thehindu.com/news/national/feeder/default.rss",
            "https://indianexpress.com/section/india/feed/",
        ],
    },
    "Entertainment": {
        "gnews_query": "Hollywood OR Bollywood OR Netflix OR box office OR celebrity",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://variety.com/feed/",
            "https://deadline.com/feed/",
        ],
    },
}

# ── Fetcher limits ─────────────────────────────────────────────────────────────
# GNews free tier: 100 req/day, max 10 articles per request
GNEWS_MAX_PER_CATEGORY  = 10   # articles fetched from GNews per category
RSS_MAX_PER_FEED        = 5    # articles fetched from each RSS feed
MAX_AGE_HOURS           = 24   # ignore articles older than this

# ── AI summarizer ──────────────────────────────────────────────────────────────
OPENROUTER_MODEL        = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
GEMINI_MODEL            = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
TOP_ARTICLES_FOR_AI     = 10   # top N articles per category sent to AI model
MAX_SUMMARY_TOKENS      = 4096
