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
- If the data is sparse, keep it short rather than padding."""

EDITORIAL_SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {
            "type": "string",
            "description": "1-2 sentence personalized intro for the week, referencing the most notable items",
        },
        "rec_blurbs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Exact show title as given"},
                    "blurb": {"type": "string", "description": "One spoiler-free sentence on why this user might like it"},
                },
                "required": ["title", "blurb"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["intro", "rec_blurbs"],
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
        "recommendations": [
            {"title": r.get("title"), "rating": r.get("vote"),
             "because_user_watches": r.get("seed")}
            for r in sections.get("recs", [])
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

    Returns {"intro": str, "rec_blurbs": {title_lower: blurb}}.
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
    blurbs = {}
    for b in result.get("rec_blurbs") or []:
        if isinstance(b, dict) and b.get("title") and b.get("blurb"):
            blurbs[str(b["title"]).strip().lower()] = str(b["blurb"]).strip()
    return {"intro": result["intro"].strip(), "rec_blurbs": blurbs}
