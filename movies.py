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
from typing import Any, Dict, List, Optional

import requests

TMDB_BASE = "https://api.themoviedb.org/3"
MEDIA_TYPE = "movie"


def _get(path: str, **params) -> Dict[str, Any]:
    params.update(api_key=os.getenv("TMDB_API_KEY", "").strip(), language="en-US")
    r = requests.get(f"{TMDB_BASE}{path}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


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
            "next_air_date": m.get("release_date"),
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
