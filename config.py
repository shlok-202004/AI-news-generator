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
    # ── Original 6 ────────────────────────────────────────────────────────────
    "Tech": {
        "gnews_query": "technology OR software OR hardware OR gadgets OR computing OR semiconductors OR smartphones",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://techcrunch.com/feed/",
            "https://www.wired.com/feed/rss",
            "https://feeds.arstechnica.com/arstechnica/index",
            "https://www.theverge.com/rss/index.xml",
        ],
    },
    "AI": {
        "gnews_query": "artificial intelligence OR machine learning OR large language model OR generative AI OR AI model OR neural network OR AI regulation OR AI research",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://venturebeat.com/category/ai/feed/",
            "https://www.technologyreview.com/feed/",
        ],
    },
    "Stock Market": {
        "gnews_query": "stock market OR equities OR Wall Street OR S&P 500 OR earnings OR IPO OR interest rates OR Federal Reserve OR inflation OR bonds",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ],
    },
    "Geopolitics": {
        "gnews_query": "geopolitics OR international relations OR diplomacy OR sanctions OR war OR conflict OR treaty OR United Nations OR foreign policy OR military",
        "gnews_lang": "en",
        "rss_feeds": [
            "http://feeds.bbci.co.uk/news/world/rss.xml",
            "https://www.theguardian.com/world/rss",
            "https://www.aljazeera.com/xml/rss/all.xml",
        ],
    },
    "India Politics": {
        "gnews_query": "India OR Indian government OR Modi OR BJP OR Congress party OR Indian parliament OR Indian economy OR Indian election OR Supreme Court India OR Indian foreign policy",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://www.thehindu.com/news/national/feeder/default.rss",
            "https://indianexpress.com/section/india/feed/",
        ],
    },
    "Entertainment": {
        "gnews_query": "entertainment OR Hollywood OR Bollywood OR streaming OR box office OR music OR celebrity OR film OR television OR OTT",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://variety.com/feed/",
            "https://deadline.com/feed/",
        ],
    },
    # ── Startups & VC ─────────────────────────────────────────────────────────
    "Startups & VC": {
        "gnews_query": "startup OR venture capital OR funding round OR seed round OR unicorn OR accelerator OR angel investment OR Series A OR Series B OR product launch",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://techcrunch.com/category/startups/feed/",
            "https://techcrunch.com/category/venture/feed/",
            "https://news.crunchbase.com/feed/",
        ],
    },
    # ── Science & Tech ────────────────────────────────────────────────────────
    "Science & Space": {
        "gnews_query": "science OR space exploration OR NASA OR SpaceX OR astronomy OR physics OR biology OR scientific discovery OR research breakthrough OR rocket launch",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://www.nasa.gov/rss/dyn/breaking_news.rss",
            "https://www.sciencedaily.com/rss/all.xml",
            "https://feeds.arstechnica.com/arstechnica/science",
            "https://www.space.com/feeds/all",
        ],
    },
    "Cybersecurity": {
        "gnews_query": "cybersecurity OR data breach OR ransomware OR hacking OR vulnerability OR malware OR phishing OR cyber attack OR zero-day OR information security",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.feedburner.com/TheHackersNews",
            "https://www.bleepingcomputer.com/feed/",
            "https://krebsonsecurity.com/feed/",
        ],
    },
    "Automotive & EV": {
        "gnews_query": "electric vehicle OR EV OR Tesla OR autonomous vehicle OR self-driving OR automotive OR battery technology OR car industry OR EV charging",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://electrek.co/feed/",
            "https://insideevs.com/feed/",
        ],
    },
    "Gaming": {
        "gnews_query": "video games OR gaming OR esports OR PlayStation OR Xbox OR Nintendo OR game studio OR game release OR game industry OR PC gaming",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.ign.com/ign/all",
            "https://www.polygon.com/rss/index.xml",
            "https://kotaku.com/feed/rss",
        ],
    },
    # ── Health ────────────────────────────────────────────────────────────────
    "Health & Medicine": {
        "gnews_query": "health OR medicine OR medical research OR clinical trial OR FDA OR pharmaceutical OR disease OR treatment OR public health OR healthcare OR mental health",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://www.statnews.com/feed/",
            "https://www.sciencedaily.com/rss/health_medicine.xml",
            "https://www.healthline.com/rss/health-news",
        ],
    },
    # ── Politics & World ──────────────────────────────────────────────────────
    "US Politics": {
        "gnews_query": "US politics OR White House OR Congress OR Senate OR Republican OR Democrat OR Washington DC OR American election OR US policy OR Supreme Court",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.npr.org/1014/rss.xml",
            "https://thehill.com/news/feed/",
        ],
    },
    "UK Politics": {
        "gnews_query": "UK politics OR British government OR Parliament OR Prime Minister OR Conservative OR Labour OR Downing Street OR British election OR UK economy",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.bbci.co.uk/news/politics/rss.xml",
            "https://www.theguardian.com/politics/rss",
        ],
    },
    "Middle East": {
        "gnews_query": "Middle East OR Israel OR Palestine OR Gaza OR Iran OR Saudi Arabia OR Egypt OR Iraq OR Syria OR Yemen OR Lebanon OR Persian Gulf",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
            "https://www.theguardian.com/world/middleeast/rss",
        ],
    },
    "China & Asia": {
        "gnews_query": "China OR Taiwan OR Japan OR South Korea OR ASEAN OR Xi Jinping OR Chinese economy OR Indo-Pacific OR Asia Pacific OR Hong Kong OR trade war",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
            "https://asia.nikkei.com/rss/feed/nar",
        ],
    },
    "Europe": {
        "gnews_query": "Europe OR European Union OR NATO OR Germany OR France OR European Parliament OR EU policy OR Eurozone OR European election OR EU regulation",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.bbci.co.uk/news/world/europe/rss.xml",
            "https://www.politico.eu/feed/",
        ],
    },
    "Defence & Military": {
        "gnews_query": "military OR defence OR defense OR army OR navy OR air force OR weapons OR Pentagon OR nuclear OR missile OR armed forces OR defence spending",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://www.defenseone.com/rss/all/",
            "https://breakingdefense.com/feed/",
        ],
    },
    "Africa": {
        "gnews_query": "Africa OR African Union OR South Africa OR Nigeria OR Kenya OR Ethiopia OR Sahel OR African politics OR African economy OR sub-Saharan",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.bbci.co.uk/news/world/africa/rss.xml",
            "https://www.theguardian.com/world/africa/rss",
        ],
    },
    "Latin America": {
        "gnews_query": "Latin America OR Brazil OR Mexico OR Argentina OR Colombia OR Venezuela OR South America OR LATAM OR Caribbean",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.bbci.co.uk/news/world/latin_america/rss.xml",
            "https://www.theguardian.com/world/americas/rss",
        ],
    },
    # ── Lifestyle & Culture ───────────────────────────────────────────────────
    "Sports": {
        "gnews_query": "sports OR football OR cricket OR basketball OR tennis OR Formula 1 OR Olympics OR Premier League OR World Cup OR athletics OR soccer",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://feeds.bbci.co.uk/sport/rss.xml",
            "https://www.skysports.com/rss/12040",
        ],
    },
    "Business & Leadership": {
        "gnews_query": "business OR corporate strategy OR CEO OR merger OR acquisition OR company earnings OR leadership OR management OR Fortune 500 OR enterprise",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://fortune.com/feed/",
            "https://www.businessinsider.com/rss",
            "https://feeds.feedburner.com/fastcompany/headlines",
        ],
    },
    "Climate & Environment": {
        "gnews_query": "climate change OR environment OR renewable energy OR carbon emissions OR sustainability OR global warming OR clean energy OR solar OR wind energy OR climate policy",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://www.theguardian.com/environment/rss",
            "https://insideclimatenews.org/feed/",
        ],
    },
    "Media & Journalism": {
        "gnews_query": "media OR journalism OR press freedom OR streaming OR social media OR misinformation OR newspaper OR broadcast OR digital media OR content",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://www.niemanlab.org/feed/",
            "https://digiday.com/feed/",
        ],
    },
    "Education & EdTech": {
        "gnews_query": "education OR edtech OR university OR school OR online learning OR higher education OR AI in education OR student loans OR curriculum OR ed-tech",
        "gnews_lang": "en",
        "rss_feeds": [
            "https://campustechnology.com/rss-feeds/news.aspx",
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
