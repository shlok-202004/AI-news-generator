import logging
import re
import time
import warnings

from openai import OpenAI

# Only import Gemini SDK if actually using it (avoids deprecation spam when on OpenRouter)
from config import AI_PROVIDER as _AI_PROVIDER
if _AI_PROVIDER.lower() == "gemini":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as genai

from config import (
    AI_PROVIDER, OPENROUTER_API_KEY, OPENROUTER_MODEL,
    GEMINI_API_KEY, GEMINI_MODEL, MAX_SUMMARY_TOKENS,
)
from fetchers.gnews_fetcher import Article

logger = logging.getLogger(__name__)

if AI_PROVIDER.lower() == "openrouter":
    _openrouter_client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )
elif AI_PROVIDER.lower() == "gemini":
    genai.configure(api_key=GEMINI_API_KEY)
    _gemini_client = genai.GenerativeModel(GEMINI_MODEL)

# ── Category cosmetics ─────────────────────────────────────────────────────────
CATEGORY_EMOJIS: dict[str, str] = {
    "Tech":           "🖥️",
    "AI":             "🤖",
    "Stock Market":   "📈",
    "Geopolitics":    "🌍",
    "India Politics": "🇮🇳",
    "Entertainment":  "🎬",
}

# ── Prompts ────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a sharp news analyst writing a daily briefing that renders in Discord.

OUTPUT FORMAT — follow exactly, character-for-character:

[SECTION: {EMOJI} {CATEGORY NAME}]
[BIGPIC: One crisp sentence: what does today's news mean at a macro level?]

🔹 **[Punchy, rewritten story headline]** `[SENTIMENT]`
> [1-2 sentence insight — what happened and why it matters]
> 📎 [Source Name](ARTICLE_URL)

🔹 **[Next story headline]** `[SENTIMENT]`
> [insight]
> 📎 [Source Name](URL)

SENTIMENT TAGS — pick exactly one per story, placed at end of the headline line:
- General categories  →  `🟢` positive/good news  |  `🟡` neutral/mixed  |  `🔴` negative/concerning
- Stock Market only   →  `📈` bullish  |  `⚖️` neutral  |  `📉` bearish
- Geopolitics only    →  `🟢` diplomatic/resolved  |  `🟡` tension/developing  |  `🔴` conflict/escalation

RULES:
- Output one [SECTION:] block per category, in the order given.
- Every story uses exactly the 3-line format: 🔹 headline + sentiment, > insight, > 📎 link.
- Keep each insight under 35 words.
- Do NOT output anything outside these blocks — no intro, no outro, no extra markdown.
- Separate category blocks with a single blank line."""


_DEEP_DIVE_PROMPT = """\
You are an investigative analyst writing a deep-dive for Discord.

OUTPUT FORMAT (renders in Discord — follow exactly):

**📍 Overview**
[2-3 sentences: current situation and context]

**📋 Key Developments**
🔹 **[Development headline]** `[🟢/🟡/🔴]`
> [2-3 sentence explanation with specifics]
> 📎 [Source Name](URL)

**🔎 Why It Matters**
> [1 paragraph: broader significance and who is affected]

**👁️ What to Watch**
• [Thing to monitor 1]
• [Thing to monitor 2]
• [Thing to monitor 3]

RULES:
- Be analytical, not just descriptive. Use specific facts and numbers.
- Keep each development under 50 words.
- Output only the briefing — no intro, no outro."""


def _build_user_prompt(selected: dict[str, list[Article]]) -> str:
    lines: list[str] = ["Produce today's daily briefing from the articles below.\n"]

    for category, articles in selected.items():
        emoji = CATEGORY_EMOJIS.get(category, "📰")
        lines.append(f"=== {emoji} {category.upper()} ===")
        for i, a in enumerate(articles, 1):
            desc = a.description[:1500].strip()  # use full scraped text
            lines.append(
                f"{i}. Title:  {a.title}\n"
                f"   Source: {a.source}\n"
                f"   URL:    {a.url}\n"
                f"   Content: {desc or 'N/A'}\n"
            )
        lines.append("")

    return "\n".join(lines)


# ── Retry wrapper ──────────────────────────────────────────────────────────────
_MAX_RETRIES = 3
_RETRY_DELAYS = [5, 15, 45]


def _call_ai(user_prompt: str, system_prompt: str = _SYSTEM_PROMPT) -> str:
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            if AI_PROVIDER.lower() == "openrouter":
                return _call_openrouter(user_prompt, system_prompt)
            elif AI_PROVIDER.lower() == "gemini":
                return _call_gemini(user_prompt, system_prompt)
            else:
                raise ValueError(f"Unknown AI_PROVIDER: {AI_PROVIDER}")
        except Exception as exc:
            logger.exception("Error calling AI API")
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                wait = _RETRY_DELAYS[attempt]
                logger.warning("Retrying in %ds… (attempt %d/%d)", wait, attempt + 1, _MAX_RETRIES)
                time.sleep(wait)

    raise RuntimeError(f"AI API failed after {_MAX_RETRIES} attempts: {last_exc}")


def _call_openrouter(user_prompt: str, system_prompt: str = _SYSTEM_PROMPT) -> str:
    response = _openrouter_client.chat.completions.create(
        model=OPENROUTER_MODEL,
        max_tokens=MAX_SUMMARY_TOKENS,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    )
    text = response.choices[0].message.content.strip()
    logger.info("OpenRouter responded (%d chars, finish_reason=%s)",
                len(text), response.choices[0].finish_reason)
    return text


def _call_gemini(user_prompt: str, system_prompt: str = _SYSTEM_PROMPT) -> str:
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    response = _gemini_client.generate_content(
        full_prompt,
        generation_config=genai.types.GenerationConfig(max_output_tokens=MAX_SUMMARY_TOKENS),
    )
    text = response.text.strip()
    logger.info("Gemini responded (%d chars)", len(text))
    return text


# ── Response validator ─────────────────────────────────────────────────────────

def _validate_response(text: str) -> bool:
    has_section = "[SECTION:" in text
    has_bigpic  = "[BIGPIC:"  in text
    has_story   = "🔹" in text

    if not (has_section and has_story):
        logger.warning(
            "AI response looks malformed (section=%s, bigpic=%s, story=%s)",
            has_section, has_bigpic, has_story,
        )
        return False
    return True


# ── Split briefing into per-category chunks ────────────────────────────────────

_SECTION_MARKER = re.compile(r"^\[SECTION:")


def _split_by_category(briefing: str) -> list[str]:
    sections: list[str] = []
    current_lines: list[str] = []

    for line in briefing.splitlines():
        if _SECTION_MARKER.match(line.strip()) and current_lines:
            sections.append("\n".join(current_lines).strip())
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append("\n".join(current_lines).strip())

    return [s for s in sections if s]


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_briefing(selected: dict[str, list[Article]]) -> list[str]:
    """
    Generate the daily briefing from pre-filtered articles.
    Returns a list of HTML strings (one per category section).
    """
    if not selected:
        raise ValueError("generate_briefing called with empty article dict")

    logger.info(
        "Sending %d categories (%d total articles) to %s",
        len(selected),
        sum(len(v) for v in selected.values()),
        AI_PROVIDER.upper(),
    )

    user_prompt = _build_user_prompt(selected)
    raw_response = _call_ai(user_prompt)

    if not _validate_response(raw_response):
        logger.error("Validation failed. Raw AI output:\n%s", raw_response[:500])

    sections = _split_by_category(raw_response)

    if not sections:
        raise RuntimeError("AI response could not be split into sections")

    logger.info("Briefing split into %d section(s)", len(sections))
    return sections


def generate_deep_dive(topic: str, articles: list[Article]) -> str:
    """Generate a single-topic deep-dive for the /summary command."""
    lines = [f"Generate a deep-dive on the topic: **{topic}**\n"]
    for i, a in enumerate(articles, 1):
        desc = a.description[:1500].strip()
        lines.append(
            f"{i}. Title:   {a.title}\n"
            f"   Source:  {a.source}\n"
            f"   URL:     {a.url}\n"
            f"   Content: {desc or 'N/A'}\n"
        )
    user_prompt = "\n".join(lines)
    result = _call_ai(user_prompt, system_prompt=_DEEP_DIVE_PROMPT)
    return result[:4000]  # Discord embed description limit is 4096
