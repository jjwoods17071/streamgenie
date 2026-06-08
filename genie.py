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
judging from their watchlist AND user_feedback (their 👍/👎 on past picks) — \
likes are positive taste signals; avoid anything resembling the dislikes. Fit \
beats rating. Only ever pick titles that appear in recommendation_candidates, \
spelled exactly as given.
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
            {"date": g.get("date"), "league": g.get("league"),
             "matchup": g.get("matchup"), "network": g.get("network") or None}
            for g in sections.get("games", [])
        ],
        "leaving_soon": [
            {"title": e.get("title"), "service": e.get("provider_name"),
             "date": str(e.get("leaving_date"))}
            for e in sections.get("leaving", [])
        ],
        "user_watchlist": sections.get("watchlist_titles", []),
        "user_feedback": sections.get("rec_feedback") or {},
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
- You can take actions with your tools: add shows, remove shows/teams, change \
which app a show is tracked on, and mark a show fully caught up. Use the tmdb_id \
from the user context when the show is already in the watchlist; use search_show \
to resolve new shows. The context can be a few minutes stale — if the user refers \
to a show that isn't in it (e.g. one just added), resolve it with search_show \
rather than telling them it doesn't exist. After acting, confirm plainly what you \
did. If a search returns several plausible matches, ask which one before adding. \
Never remove anything unless the user explicitly asked for that show/team to be \
removed."""


GENIE_TOOLS = [
    {"name": "search_show",
     "description": "Search TMDB for a TV show by name. Use to resolve a show the user wants to add (or asks about) that is not already in their watchlist. Returns up to 5 candidates with tmdb_id, first air year, and a short overview.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Show name to search for"}},
         "required": ["query"]}},
    {"name": "add_show",
     "description": "Add a show to the user's watchlist, tracked on a specific app. Resolve tmdb_id first (from user context or search_show). provider_name examples: Netflix, Prime Video, Hulu, Max, Paramount+, Apple TV+, Peacock, Disney+, Broadcast TV.",
     "input_schema": {"type": "object", "properties": {
         "tmdb_id": {"type": "integer"},
         "provider_name": {"type": "string", "description": "The app the user will watch it on"}},
         "required": ["tmdb_id", "provider_name"]}},
    {"name": "remove_show",
     "description": "Remove a show or followed team from the watchlist. tmdb_id comes from the user context (negative ids are sports follows). Only when the user explicitly asks.",
     "input_schema": {"type": "object", "properties": {
         "tmdb_id": {"type": "integer"}},
         "required": ["tmdb_id"]}},
    {"name": "set_provider",
     "description": "Change which app a watchlist show is tracked on.",
     "input_schema": {"type": "object", "properties": {
         "tmdb_id": {"type": "integer"},
         "provider_name": {"type": "string"}},
         "required": ["tmdb_id", "provider_name"]}},
    {"name": "mark_caught_up",
     "description": "Mark every already-aired episode of a show as watched (the user says they are caught up). Optionally only through a given season.",
     "input_schema": {"type": "object", "properties": {
         "tmdb_id": {"type": "integer"},
         "through_season": {"type": "integer", "description": "Optional: last season to mark"}},
         "required": ["tmdb_id"]}},
]


def _exec_tool(client, user_id: str, name: str, inp: Dict[str, Any]) -> str:
    """Execute one Genie tool against TMDB/Supabase. Returns a plain-text result."""
    import datetime as _dt
    tid = int(inp.get("tmdb_id") or 0)

    if name == "search_show":
        r = _tmdb_get("/search/tv", query=inp.get("query", ""))
        out = [{"tmdb_id": x.get("id"), "title": x.get("name"),
                "year": (x.get("first_air_date") or "")[:4],
                "overview": (x.get("overview") or "")[:140]}
               for x in r.get("results", [])[:5]]
        return json.dumps(out) if out else "No matches found."

    if name == "add_show":
        d = _tmdb_get(f"/tv/{tid}")
        nxt = d.get("next_episode_to_air") or {}
        row = {"user_id": user_id, "tmdb_id": tid, "title": d.get("name") or f"Show {tid}",
               "region": "US", "on_provider": True,
               "next_air_date": nxt.get("air_date"),
               "overview": d.get("overview") or "",
               "poster_path": d.get("poster_path"),
               "provider_name": inp.get("provider_name") or "Multiple Providers"}
        client.table("shows").upsert(row, on_conflict="user_id,tmdb_id,provider_name").execute()
        return f"Added '{row['title']}' on {row['provider_name']}."

    if name == "remove_show":
        got = client.table("shows").select("title").eq("user_id", user_id).eq("tmdb_id", tid).execute().data
        if not got:
            return "That show isn't in the watchlist."
        client.table("shows").delete().eq("user_id", user_id).eq("tmdb_id", tid).execute()
        return f"Removed '{got[0]['title']}' from the watchlist."

    if name == "set_provider":
        prov = inp.get("provider_name") or ""
        got = client.table("shows").select("title").eq("user_id", user_id).eq("tmdb_id", tid).execute().data
        if not got:
            return "That show isn't in the watchlist."
        client.table("shows").update({"provider_name": prov}).eq("user_id", user_id).eq("tmdb_id", tid).execute()
        return f"'{got[0]['title']}' is now tracked on {prov}."

    if name == "mark_caught_up":
        import watched as _watched
        d = _tmdb_get(f"/tv/{tid}")
        today = _dt.date.today().isoformat()
        through = int(inp.get("through_season") or 999)
        total = 0
        for s in d.get("seasons", []):
            sn = s.get("season_number")
            if not sn or sn > through:  # skip specials (0) and beyond requested
                continue
            sd = _tmdb_get(f"/tv/{tid}/season/{sn}")
            eps = [e["episode_number"] for e in sd.get("episodes", [])
                   if e.get("air_date") and e["air_date"] <= today]
            if eps:
                _watched.set_season(client, user_id, tid, sn, eps, True)
                total += len(eps)
        return f"Marked {total} aired episode(s) of '{d.get('name')}' as watched."

    return f"Unknown tool: {name}"


def _tmdb_get(path: str, **params) -> Dict[str, Any]:
    params.update(api_key=os.getenv("TMDB_API_KEY", "").strip(), language="en-US")
    r = requests.get(f"https://api.themoviedb.org/3{path}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def chat(history: list, context: Dict[str, Any], client=None, user_id=None, log=print) -> Optional[Dict[str, Any]]:
    """One Ask-Genie turn. history = [{"role": "user"|"assistant", "content": str}].

    Returns {"text": str, "acted": bool} or None. With client+user_id, Genie gets
    tools (add/remove/set-provider/mark-watched/search) and runs a bounded agentic
    loop (Jan Bot pattern). Claude primary (static prompt cached; volatile user
    context after it) → Gemini failover (Q&A only, no tools) → None.
    """
    ctx = "Current user context (refreshed every ~15 min):\n" + _week_payload(context) \
        + "\nFull watchlist with apps: " + json.dumps(context.get("watchlist", []), sort_keys=True) \
        + "\nFollowed teams/series: " + json.dumps(context.get("sports_follows", []), sort_keys=True)
    msgs = [{"role": m["role"], "content": m["content"]} for m in history][-12:]

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        try:
            import anthropic
            ac = anthropic.Anthropic(api_key=api_key)
            tools = GENIE_TOOLS if (client is not None and user_id) else []
            convo = list(msgs)
            acted = False
            for _hop in range(6):  # bounded agentic loop
                response = ac.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=1024,
                    system=[
                        {"type": "text", "text": CHAT_SYSTEM_PROMPT,
                         "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": ctx},
                    ],
                    tools=tools,
                    messages=convo,
                )
                if response.stop_reason == "tool_use":
                    convo.append({"role": "assistant", "content": response.content})
                    results = []
                    for b in response.content:
                        if b.type == "tool_use":
                            try:
                                out = _exec_tool(client, user_id, b.name, dict(b.input))
                                acted = True
                                log(f"genie tool: {b.name}({b.input}) -> {out[:80]}")
                            except Exception as e:
                                out = f"Error: {e}"
                                log(f"genie tool FAILED: {b.name}: {e}")
                            results.append({"type": "tool_result",
                                            "tool_use_id": b.id, "content": out})
                    convo.append({"role": "user", "content": results})
                    continue
                text = next((b.text for b in response.content if b.type == "text"), "")
                if text:
                    return {"text": text, "acted": acted}
                break
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
            return {"text": r.json()["candidates"][0]["content"]["parts"][0]["text"],
                    "acted": False}
        except Exception as e:
            log(f"genie chat: Gemini failed ({e})")
    return None
