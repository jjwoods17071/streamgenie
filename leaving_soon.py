"""
Leaving Soon — admin-curated list of shows leaving streaming providers.

Populates the `leaving_soon` table (admin panel) and exposes helpers for the
user-facing "Leaving Soon" display. Self-contained: does its own TMDB lookups
(TMDB_API_KEY from env) and Supabase reads/writes via the passed client.
"""
import os
import datetime as dt
from typing import Optional, List, Dict, Any

import requests

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p"

# Common providers offered in the admin picker (free-text fallback via "Other…")
COMMON_PROVIDERS = [
    "Netflix", "Hulu", "Prime Video", "Disney+", "Max", "Apple TV+",
    "Paramount+", "Peacock", "Showtime", "Starz", "AMC+", "Crunchyroll",
    "Tubi", "Pluto TV", "Freevee", "discovery+", "ESPN+",
]


# --------------- TMDB ---------------
def _tmdb_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    p = {"api_key": TMDB_API_KEY, "language": "en-US"}
    if params:
        p.update(params)
    r = requests.get(f"{TMDB_BASE}{path}", params=p, timeout=15)
    r.raise_for_status()
    return r.json()


def search_shows(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Search TMDB TV shows -> [{tmdb_id, title, year, poster_path, overview}]."""
    if not query.strip():
        return []
    try:
        data = _tmdb_get("/search/tv", {"query": query, "include_adult": "false", "page": 1})
    except Exception:
        return []
    out = []
    for s in (data.get("results") or [])[:limit]:
        first_air = s.get("first_air_date") or ""
        out.append({
            "tmdb_id": s.get("id"),
            "title": s.get("name", "Unknown"),
            "year": first_air[:4] if first_air else "—",
            "poster_path": s.get("poster_path"),
            "overview": s.get("overview", ""),
        })
    return out


def poster_url(poster_path: Optional[str], size: str = "w92") -> Optional[str]:
    return f"{IMG_BASE}/{size}{poster_path}" if poster_path else None


# --------------- DB CRUD ---------------
def list_entries(client) -> List[Dict[str, Any]]:
    """All leaving_soon rows, soonest departure first."""
    try:
        r = client.table("leaving_soon").select("*").order("leaving_date", desc=False).execute()
        return r.data or []
    except Exception:
        return []


def get_active(client, within_days: Optional[int] = None) -> List[Dict[str, Any]]:
    """Entries whose leaving_date is today or later (optionally within N days)."""
    today = dt.date.today()
    rows = []
    for e in list_entries(client):
        try:
            d = dt.date.fromisoformat(str(e.get("leaving_date")))
        except Exception:
            continue
        if d < today:
            continue
        if within_days is not None and (d - today).days > within_days:
            continue
        e["_days_left"] = (d - today).days
        rows.append(e)
    return rows


def add_entry(client, tmdb_id: int, title: str, provider_name: str,
              leaving_date: str, poster_path: Optional[str]) -> tuple[bool, str]:
    """Upsert one entry (unique on tmdb_id+provider_name)."""
    try:
        payload = {
            "tmdb_id": int(tmdb_id),
            "title": title,
            "provider_name": provider_name,
            "leaving_date": leaving_date,
            "poster_path": poster_path,
        }
        client.table("leaving_soon").upsert(
            payload, on_conflict="tmdb_id,provider_name"
        ).execute()
        return True, f"Saved “{title}” leaving {provider_name} on {leaving_date}"
    except Exception as e:
        return False, f"Save failed: {e}"


def delete_entry(client, entry_id: int) -> bool:
    try:
        client.table("leaving_soon").delete().eq("id", entry_id).execute()
        return True
    except Exception:
        return False


# --------------- Admin UI ---------------
