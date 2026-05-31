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
import streamlit as st

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
def render_admin_panel(client) -> None:
    """Admin tab: search a show, set provider + leaving date, save; manage existing."""
    st.markdown("**⏳ Leaving Soon — Admin**")
    st.caption("Curate the list of shows about to leave a streaming service. Shown to all users.")

    # ---- Add new entry ----
    with st.container(border=True):
        st.markdown("**Add a show**")
        query = st.text_input("Search TV show", key="ls_search_q",
                              placeholder="e.g. Gen V")
        results = search_shows(query) if query else []

        if query and not results:
            st.caption("No matches.")

        if results:
            labels = [f"{r['title']} ({r['year']})" for r in results]
            idx = st.selectbox("Pick the show", range(len(results)),
                               format_func=lambda i: labels[i], key="ls_pick")
            chosen = results[idx]

            c1, c2, c3 = st.columns([1, 2, 2])
            with c1:
                pu = poster_url(chosen["poster_path"], "w92")
                if pu:
                    st.image(pu, width=70)
            with c2:
                prov_choice = st.selectbox("Provider", COMMON_PROVIDERS + ["Other…"],
                                           key="ls_prov")
                provider = prov_choice
                if prov_choice == "Other…":
                    provider = st.text_input("Provider name", key="ls_prov_other").strip()
            with c3:
                default_date = dt.date.today() + dt.timedelta(days=30)
                leaving_date = st.date_input("Leaving date", value=default_date,
                                             min_value=dt.date.today(), key="ls_date")

            if st.button("➕ Add to Leaving Soon", type="primary", key="ls_add"):
                if not provider:
                    st.error("Pick or type a provider.")
                else:
                    ok, msg = add_entry(client, chosen["tmdb_id"], chosen["title"],
                                        provider, leaving_date.isoformat(),
                                        chosen["poster_path"])
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    # ---- Existing entries ----
    st.markdown("**Current entries**")
    entries = list_entries(client)
    if not entries:
        st.info("No shows in Leaving Soon yet. Add one above.")
        return

    today = dt.date.today()
    for e in entries:
        with st.container(border=True):
            cols = st.columns([1, 4, 2, 1])
            with cols[0]:
                pu = poster_url(e.get("poster_path"), "w92")
                if pu:
                    st.image(pu, width=50)
            with cols[1]:
                st.markdown(f"**{e.get('title')}**")
                st.caption(f"Leaving **{e.get('provider_name')}**")
            with cols[2]:
                try:
                    d = dt.date.fromisoformat(str(e.get("leaving_date")))
                    days = (d - today).days
                    tag = "⚠️ gone" if days < 0 else (f"in {days}d" if days <= 14 else f"{days}d")
                    st.caption(f"{e.get('leaving_date')}  ·  {tag}")
                except Exception:
                    st.caption(str(e.get("leaving_date")))
            with cols[3]:
                if st.button("🗑️", key=f"ls_del_{e['id']}", help="Remove"):
                    if delete_entry(client, e["id"]):
                        st.rerun()


# --------------- User-facing display ---------------
def render_user_section(client, watchlist_tmdb_ids: Optional[set] = None,
                        within_days: int = 60) -> None:
    """Compact 'Leaving Soon' strip for the main page. Highlights watchlist hits."""
    active = get_active(client, within_days=within_days)
    if not active:
        return

    watchlist_tmdb_ids = watchlist_tmdb_ids or set()
    on_watch = [e for e in active if e.get("tmdb_id") in watchlist_tmdb_ids]

    st.markdown("### ⏳ Leaving Soon")
    if on_watch:
        titles = ", ".join(f"**{e['title']}**" for e in on_watch)
        st.warning(f"On your watchlist and leaving soon: {titles}")

    cols = st.columns(min(len(active), 5))
    for i, e in enumerate(active[:5]):
        with cols[i]:
            pu = poster_url(e.get("poster_path"), "w185")
            if pu:
                st.image(pu, use_container_width=True)
            star = "⭐ " if e.get("tmdb_id") in watchlist_tmdb_ids else ""
            st.caption(f"{star}**{e['title']}**")
            days = e.get("_days_left", 0)
            urgency = "🔴" if days <= 7 else ("🟡" if days <= 21 else "⚪")
            st.caption(f"{urgency} {e['provider_name']} · {days}d left")
