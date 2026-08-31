"""
Movies for StreamGenie.

The app was TV-only: every TMDB call hits /tv/*, and ~20 places in app.py read
"tmdb_id > 0" as "this is a TV show" (negative ids being sports follows). Movies can't
be namespaced into a numeric band the way sports were without breaking all of them, and
TMDB reuses ids across media types (movie 550 = Fight Club; tv 550 is unrelated), so a
row's identity is (tmdb_id, media_type). See migrations/2026-08-24_media_type.sql.

Runtime-agnostic (no streamlit import) so selftest and the cron path can use it.
"""
import os
import time
from typing import Any, Dict, List, Optional

import requests

import tmdb

TMDB_BASE = "https://api.themoviedb.org/3"
MEDIA_TYPE = "movie"


def _get(path: str, **params) -> Dict[str, Any]:
    """Delegates to the shared TMDB client — see tmdb.py."""
    return tmdb.get(path, **params)


def normalize(m: Dict[str, Any]) -> Dict[str, Any]:
    """TMDB movie -> the row shape the rest of the app already speaks.

    `release_date` maps onto next_air_date so date-sorting and the calendar helpers keep
    working for unreleased films; a released movie carries no future date.
    """
    rd = m.get("release_date") or ""
    return {
        "tmdb_id": m.get("id"),
        "media_type": MEDIA_TYPE,
        "title": m.get("title") or m.get("name") or "Unknown",
        "year": rd[:4] if rd else "—",
        "release_date": rd or None,
        "poster_path": m.get("poster_path"),
        "overview": m.get("overview") or "",
        "vote": m.get("vote_average") or 0,
        "votes": m.get("vote_count") or 0,
        "genre_ids": m.get("genre_ids") or [],
        "original_language": m.get("original_language"),
        "runtime": m.get("runtime"),
    }


def search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    if not (query or "").strip():
        return []
    try:
        res = _get("/search/movie", query=query, include_adult="false", page=1).get("results", [])
    except Exception:
        return []
    return [normalize(m) for m in res[:limit]]


def details(movie_id: int) -> Dict[str, Any]:
    try:
        return _get(f"/movie/{movie_id}")
    except Exception:
        return {}


def recommendations(movie_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        res = _get(f"/movie/{movie_id}/recommendations").get("results", [])
    except Exception:
        return []
    return [normalize(m) for m in res[:limit]]


def similar(movie_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        res = _get(f"/movie/{movie_id}/similar").get("results", [])
    except Exception:
        return []
    return [normalize(m) for m in res[:limit]]


def providers(movie_id: int, region: str = "US") -> List[str]:
    """Streaming services carrying the movie in `region` (flatrate only — we track
    subscriptions, not rentals)."""
    try:
        d = _get(f"/movie/{movie_id}/watch/providers").get("results", {}).get(region, {})
    except Exception:
        return []
    return [p.get("provider_name") for p in (d.get("flatrate") or []) if p.get("provider_name")]


# TMDB release_dates types
RELEASE_PREMIERE, RELEASE_LIMITED, RELEASE_THEATRICAL = 1, 2, 3
RELEASE_DIGITAL, RELEASE_PHYSICAL, RELEASE_TV = 4, 5, 6

# A bare Digital entry is usually paid VOD (rent/buy). The one that names a service in
# its note — "HBO Max", "Netflix" — is the subscription-streaming drop, which is what
# people actually wait for. Superman 2025: Digital 08-15 (PVOD) vs Digital 09-19 "HBO Max".
_TYPE_NAME = {1: "Premiere", 2: "Theatrical (limited)", 3: "Theatrical",
              4: "Digital", 5: "Physical", 6: "TV"}


def _recent_cutoff(days: int = 120) -> str:
    """A theatrical run past this is over — used to stop old films reading as in-cinemas."""
    import datetime as _dt
    return (_dt.date.today() - _dt.timedelta(days=days)).isoformat()


def release_info(movie_id: int, region: str = "US") -> Dict[str, Any]:
    """When does this movie reach streaming, and is it there yet?

    Returns theatrical/digital/streaming dates, the naming service where TMDB gives one,
    the subscription services carrying it right now, and a single `status` summarizing
    all of it: streaming | coming | theaters | unreleased | unknown.
    """
    out = {"theatrical": None, "digital": None, "streaming": None,
           "streaming_service": None, "providers": [], "status": "unknown"}
    try:
        data = _get(f"/movie/{movie_id}/release_dates").get("results", [])
    except Exception:
        return out
    entry = next((x for x in data if x.get("iso_3166_1") == region), None)
    if entry is None:
        entry = next((x for x in data if x.get("iso_3166_1") == "US"), None)

    named_service = None
    for rd in (entry or {}).get("release_dates", []):
        t, d = rd.get("type"), (rd.get("release_date") or "")[:10]
        if not d:
            continue
        note = (rd.get("note") or "").strip()
        if t in (RELEASE_THEATRICAL, RELEASE_LIMITED):
            if not out["theatrical"] or d < out["theatrical"]:
                out["theatrical"] = d
        elif t == RELEASE_DIGITAL:
            if not out["digital"] or d < out["digital"]:
                out["digital"] = d
            if note and (not named_service or d < named_service[0]):
                named_service = (d, note)
        elif t == RELEASE_TV:
            if note and (not named_service or d < named_service[0]):
                named_service = (d, note)

    if named_service:
        out["streaming"], out["streaming_service"] = named_service[0], named_service[1]
    else:
        out["streaming"] = out["digital"]

    out["providers"] = providers(movie_id, region)

    import datetime as _dt
    today = _dt.date.today().isoformat()
    if out["providers"]:
        out["status"] = "streaming"
    elif out["streaming"] and out["streaming"] > today:
        out["status"] = "coming"
    elif out["theatrical"] and out["theatrical"] > today:
        out["status"] = "unreleased"
    elif out["theatrical"] and out["theatrical"] > _recent_cutoff():
        # Only a RECENT theatrical release is plausibly still in cinemas. Without this,
        # every old film with no current provider (Michael Clayton, 2007) claimed to be
        # "in theaters" forever.
        out["status"] = "theaters"
    elif out["theatrical"]:
        out["status"] = "not_streaming"
    return out


def status_label(info: Dict[str, Any]) -> str:
    """One human line for a movie's availability."""
    s = info.get("status")
    if s == "streaming":
        provs = info.get("providers") or []
        return "🟢 Streaming now" + (f" · {provs[0]}" if provs else "")
    if s == "coming":
        svc = info.get("streaming_service")
        when = info.get("streaming") or "soon"
        return f"📅 Streaming {when}" + (f" · {svc}" if svc else "")
    if s == "theaters":
        return "🎟️ In theaters — no streaming date yet"
    if s == "not_streaming":
        return "🔍 Not on a subscription service right now"
    if s == "unreleased":
        when = info.get("theatrical")
        return f"🗓️ In theaters {when}" if when else "🗓️ Not out yet"
    return "⏳ No release date yet"


def trending(limit: int = 12) -> List[Dict[str, Any]]:
    try:
        return [normalize(m) for m in _get("/trending/movie/week").get("results", [])[:limit]]
    except Exception:
        return []


def runtime_label(minutes: Optional[int]) -> str:
    """'2h 18m' — movies have no episode count, so runtime is the size signal."""
    if not minutes:
        return ""
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m}m" if h else f"{m}m"


# ---------------- storage ----------------

def media_type_available(client) -> bool:
    """False until migrations/2026-08-24_media_type.sql has been run.

    The whole movies feature gates on this: without the column, movie rows would be
    indistinguishable from TV rows and would leak into Watch Next, the newsletter, and
    the recommendation seeds, where they'd be fetched as /tv/{id} and 404.
    """
    try:
        client.table("shows").select("media_type").limit(1).execute()
        return True
    except Exception:
        return False


def list_movies(client, user_id: str) -> List[Dict[str, Any]]:
    try:
        return (client.table("shows")
                .select("tmdb_id,title,overview,poster_path,provider_name,next_air_date,media_type")
                .eq("user_id", user_id).eq("media_type", MEDIA_TYPE)
                .order("title").execute().data or [])
    except Exception:
        return []


def add(client, user_id: str, m: Dict[str, Any], region: str = "US",
        provider_name: str = "Multiple Providers") -> bool:
    """Add one movie to the watchlist. Idempotent on (user_id, tmdb_id, media_type)."""
    try:
        row = {
            "user_id": user_id, "tmdb_id": m["tmdb_id"], "media_type": MEDIA_TYPE,
            "title": m["title"], "region": region, "on_provider": True,
            "overview": (m.get("overview") or "")[:2000],
            "poster_path": m.get("poster_path"),
            "provider_name": provider_name,
            # next_air_date holds the STREAMING date, not the theatrical one — it's the
            # date a watchlist actually cares about, and it reuses all the existing
            # date plumbing (sorting, the agenda, calendar export).
            "next_air_date": (m.get("streaming_date") or m.get("release_date")),
        }
        existing = (client.table("shows").select("id")
                    .eq("user_id", user_id).eq("tmdb_id", m["tmdb_id"])
                    .eq("media_type", MEDIA_TYPE).execute().data or [])
        if existing:
            client.table("shows").update(row).eq("id", existing[0]["id"]).execute()
        else:
            client.table("shows").insert(row).execute()
        return True
    except Exception:
        return False


def remove(client, user_id: str, tmdb_id: int) -> bool:
    try:
        (client.table("shows").delete()
         .eq("user_id", user_id).eq("tmdb_id", tmdb_id)
         .eq("media_type", MEDIA_TYPE).execute())
        return True
    except Exception:
        return False


def fetch_tv_rows(client, user_id: str, cols: str) -> List[Dict[str, Any]]:
    """Watchlist rows for the TV-only surfaces (recs seeds, the newsletter), with movies
    excluded — the module-level twin of app.list_shows. Degrades to the pre-migration
    column set so nothing breaks before 2026-08-24_media_type.sql is run."""
    try:
        rows = (client.table("shows").select(cols + ",media_type")
                .eq("user_id", user_id).execute().data or [])
    except Exception:
        rows = (client.table("shows").select(cols)
                .eq("user_id", user_id).execute().data or [])
    return [r for r in rows if (r.get("media_type") or "tv") != MEDIA_TYPE]


def enrich(client, user_id: str, region: str = "US") -> List[Dict[str, Any]]:
    """The user's movies, each with live release_info attached and their stored streaming
    date refreshed when TMDB has since published or moved one.

    Written back so the newsletter and any cron job see the same dates as the UI without
    re-querying TMDB for every consumer.
    """
    out = []
    for m in list_movies(client, user_id):
        info = release_info(m["tmdb_id"], region)
        if info.get("streaming") and info["streaming"] != m.get("next_air_date"):
            try:
                (client.table("shows").update({"next_air_date": info["streaming"]})
                 .eq("user_id", user_id).eq("tmdb_id", m["tmdb_id"])
                 .eq("media_type", MEDIA_TYPE).execute())
                m["next_air_date"] = info["streaming"]
            except Exception:
                pass
        out.append({**m, "info": info})
    return out


# Grouping order for the movies view: what you can watch tonight first, then what's
# dated, then everything you're still waiting on.
STATUS_ORDER = ["streaming", "coming", "theaters", "unreleased", "not_streaming", "unknown"]
STATUS_HEADING = {
    "streaming":     "🟢 Streaming now",
    "coming":        "📅 Coming to streaming",
    "theaters":      "🎟️ In theaters",
    "unreleased":    "🗓️ Not out yet",
    "not_streaming": "🔍 Not currently streaming",
    "unknown":       "⏳ No date yet",
}


def group_by_status(enriched: List[Dict[str, Any]]) -> List[tuple]:
    """[(status, heading, [movies])] in STATUS_ORDER, skipping empty groups."""
    buckets: Dict[str, list] = {s: [] for s in STATUS_ORDER}
    for m in enriched:
        buckets.setdefault(m["info"].get("status") or "unknown", []).append(m)
    for s, items in buckets.items():
        items.sort(key=lambda x: (x["info"].get("streaming") or "9999", x["title"].lower()))
    return [(s, STATUS_HEADING.get(s, s), buckets[s]) for s in STATUS_ORDER if buckets.get(s)]


def newly_streaming(enriched: List[Dict[str, Any]], within_days: int = 21) -> List[Dict[str, Any]]:
    """Tracked movies that reached a subscription service in the last `within_days` —
    the "it's finally out" moment worth telling someone about."""
    import datetime as _dt
    cutoff = (_dt.date.today() - _dt.timedelta(days=within_days)).isoformat()
    return [m for m in enriched
            if m["info"].get("status") == "streaming"
            and (m["info"].get("streaming") or "") >= cutoff]
