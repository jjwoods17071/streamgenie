"""
Genie — StreamGenie's editorial AI agent.

Mirrors the Jan Bot architecture from the OKS Shop Assistant:
  • Named persona, honest about being AI (disclosure rendered in the newsletter)
  • Claude (Haiku 4.5) primary via the Anthropic SDK, with prompt caching on the
    static system prompt
  • Gemini failover when Claude is unavailable (GEMINI_API_KEY, optional)
  • Guardrailed system prompt: only discuss provided data, no spoilers, never
    invent air dates / networks / availability
  • Graceful degradation: no API key (or any error) → returns None and the
    newsletter renders without editorial copy

One call per user per week (Sunday newsletter), so cost is a few cents/month.

Env: ANTHROPIC_API_KEY (primary), GEMINI_API_KEY (optional failover).
"""
import json
import os
from typing import Any, Dict, Optional

import requests

CLAUDE_MODEL = os.getenv("GENIE_CLAUDE_MODEL", "claude-haiku-4-5")
GEMINI_MODEL = os.getenv("GENIE_GEMINI_MODEL", "gemini-2.5-flash")

# Static system prompt — keep this byte-stable so prompt caching can engage
# (volatile per-user data goes in the user message, after the cached prefix).
SYSTEM_PROMPT = """You are Genie, the friendly TV-buff assistant inside StreamGenie, \
a personal streaming tracker. You write short editorial copy for a weekly email \
newsletter summarizing one user's week in streaming.

Rules you must always follow:
- Only reference the shows, games, dates, networks, and apps provided in the data. \
Never invent air dates, networks, scores, episode details, or availability.
- NO SPOILERS. Never reveal plot points, deaths, twists, or outcomes — not even \
for older seasons. Describe shows by tone, genre, and reputation only.
- Be warm, concise, and a little playful. No hype words like "epic" or "must-see" \
spam. One emoji maximum across the whole intro, none in blurbs.
- You are an AI assistant and never claim to be human.
- Write at most 2 sentences for the intro and 1 sentence per recommendation blurb.
- For recommendations: choose the 3 candidates that best fit this user's taste, \
judging from their watchlist — fit beats rating. Only ever pick titles that appear \
in recommendation_candidates, spelled exactly as given.
- If the data is sparse, keep it short rather than padding."""

EDITORIAL_SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {
            "type": "string",
            "description": "1-2 sentence personalized intro for the week, referencing the most notable items",
        },
        "picks": {
            "type": "array",
            "description": "The 3 best-fit recommendations chosen from recommendation_candidates, best first",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Exact candidate title as given"},
                    "blurb": {"type": "string", "description": "One spoiler-free sentence on why this user might like it"},
                },
                "required": ["title", "blurb"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["intro", "picks"],
    "additionalProperties": False,
}


def _week_payload(sections: Dict[str, Any]) -> str:
    """Compact, deterministic JSON of the user's week for the model."""
    data = {
        "week": f"{sections.get('week_start')} to {sections.get('week_end')}",
        "episodes_airing": [
            {"title": r.get("title"), "date": r.get("next_air_date"),
             "app": r.get("provider_name") or None}
            for r in sections.get("airing", [])
        ],
        "premieres_finales": sections.get("highlights", []),
        "games": [
            {"date": g.get("date"), "matchup": g.get("matchup"),
             "network": g.get("network") or None}
            for g in sections.get("games", [])
        ],
        "leaving_soon": [
            {"title": e.get("title"), "service": e.get("provider_name"),
             "date": str(e.get("leaving_date"))}
            for e in sections.get("leaving", [])
        ],
        "user_watchlist": sections.get("watchlist_titles", []),
        "recommendation_candidates": [
            {"title": r.get("title"), "rating": r.get("vote"),
             "because_user_watches": r.get("seed")}
            for r in (sections.get("rec_candidates") or sections.get("recs", []))
        ],
    }
    return json.dumps(data, sort_keys=True)


def _ask_claude(payload: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    import anthropic  # local import so the app runs without the package installed
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        output_config={"format": {"type": "json_schema", "schema": EDITORIAL_SCHEMA}},
        messages=[{
            "role": "user",
            "content": "Write the weekly newsletter editorial for this user's week:\n" + payload,
        }],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(text) if text else None


def _ask_gemini(payload: str) -> Optional[Dict[str, Any]]:
    """Failover, same pattern as Jan Bot's chatWithGemini."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        params={"key": api_key},
        json={
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{
                "text": "Write the weekly newsletter editorial for this user's week:\n"
                        + payload}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "intro": {"type": "STRING"},
                        "rec_blurbs": {"type": "ARRAY", "items": {
                            "type": "OBJECT",
                            "properties": {"title": {"type": "STRING"},
                                           "blurb": {"type": "STRING"}},
                            "required": ["title", "blurb"]}},
                    },
                    "required": ["intro", "rec_blurbs"],
                },
            },
        },
        timeout=30,
    )
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def generate_editorial(sections: Dict[str, Any], log=print) -> Optional[Dict[str, Any]]:
    """Genie's editorial for one user's newsletter, or None (newsletter still sends).

    Returns {"intro": str, "picks": [title_lower, ...], "rec_blurbs": {title_lower: blurb}}
    — picks are Genie's taste-curated choices from the candidate pool, best first.
    Claude primary → Gemini failover → None.
    """
    payload = _week_payload(sections)
    result = None
    try:
        result = _ask_claude(payload)
    except Exception as e:
        log(f"genie: Claude failed ({e}); trying Gemini")
    if result is None:
        try:
            result = _ask_gemini(payload)
        except Exception as e:
            log(f"genie: Gemini failed ({e})")
    if not result or not isinstance(result.get("intro"), str):
        return None
    picks, blurbs = [], {}
    for b in result.get("picks") or result.get("rec_blurbs") or []:
        if isinstance(b, dict) and b.get("title") and b.get("blurb"):
            key = str(b["title"]).strip().lower()
            picks.append(key)
            blurbs[key] = str(b["blurb"]).strip()
    return {"intro": result["intro"].strip(), "picks": picks, "rec_blurbs": blurbs}


# ---------------- Ask Genie (in-app chat) ----------------

CHAT_SYSTEM_PROMPT = """You are Genie, the friendly TV-buff AI assistant inside \
StreamGenie, a personal streaming tracker. You chat with the user about their \
watchlist, followed sports teams, and what to watch.

Rules you must always follow:
- Ground every answer in the user context provided. If something isn't in the \
context, say you don't have it rather than guessing — never invent air dates, \
networks, scores, or availability.
- NO SPOILERS, ever. Describe shows by tone, genre, and reputation only.
- You are an AI assistant and never claim to be human.
- Be warm, concise, and a little playful. Short answers for short questions. \
Use markdown lists when listing shows or games.
- When recommending what to watch tonight, prefer their own watchlist (unwatched \
or airing soon) before suggesting anything new.
- You cannot yet take actions (adding shows, marking episodes watched) — if \
asked, explain how to do it in the app instead."""


def chat(history: list, context: Dict[str, Any], log=print) -> Optional[str]:
    """One Ask-Genie turn. history = [{"role": "user"|"assistant", "content": str}].

    Claude primary (static prompt cached; volatile user context after it) →
    Gemini failover → None.
    """
    ctx = "Current user context (refreshed every ~15 min):\n" + _week_payload(context) \
        + "\nFull watchlist with apps: " + json.dumps(context.get("watchlist", []), sort_keys=True) \
        + "\nFollowed teams/series: " + json.dumps(context.get("sports_follows", []), sort_keys=True)
    msgs = [{"role": m["role"], "content": m["content"]} for m in history][-12:]

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                system=[
                    {"type": "text", "text": CHAT_SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": ctx},
                ],
                messages=msgs,
            )
            text = next((b.text for b in response.content if b.type == "text"), "")
            if text:
                return text
        except Exception as e:
            log(f"genie chat: Claude failed ({e}); trying Gemini")

    gem_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gem_key:
        try:
            contents = [{"role": "model" if m["role"] == "assistant" else "user",
                         "parts": [{"text": m["content"]}]} for m in msgs]
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                params={"key": gem_key},
                json={"system_instruction": {"parts": [{"text": CHAT_SYSTEM_PROMPT + "\n\n" + ctx}]},
                      "contents": contents},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            log(f"genie chat: Gemini failed ({e})")
    return None
