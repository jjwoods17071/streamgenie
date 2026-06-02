import os
import sqlite3
import datetime as dt
import requests
import streamlit as st
import json
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from supabase import create_client, Client
import auth  # Authentication module
import notifications  # Notifications module
import scheduled_tasks  # Background task scheduler
import preferences  # User notification preferences
import show_status  # Show status tracking from TMDB
import leaving_soon  # Admin-curated "leaving soon" list
import watched  # Watched-episode tracking
import discover  # Provider discovery + Netflix history import
import dismissed  # "Not interested" dismissals for discovery carousels
import sports  # Follow an NFL team like a show (ESPN API + 506sports maps)

# Load environment variables
load_dotenv()

# --------------- CONFIG ---------------
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"
DEFAULT_REGION = os.getenv("TMDB_REGION", "US").upper()
DEFAULT_PROVIDER = "Netflix"
LOGO_OVERRIDES_FILE = "logo_overrides.json"
DELETED_PROVIDERS_FILE = "deleted_providers.json"
USER_SETTINGS_FILE = "user_settings.json"
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "notifications@streamgenie.app").strip()

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Default user ID for single-user mode (fallback if no auth)
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

def get_user_id() -> str:
    """Get the current user ID (authenticated user or default)"""
    user_id = auth.get_user_id()
    return user_id if user_id else DEFAULT_USER_ID

# --------------- MATERIAL ICONS MAPPING ---------------
# Streamlit Material Icons for a modern, professional look
# Usage: st.button(f"{ICONS['settings']} Settings")
ICONS = {
    # Core UI
    "tv": ":material/tv:",
    "movie": ":material/movie:",
    "calendar": ":material/calendar_today:",
    "schedule": ":material/schedule:",
    "settings": ":material/settings:",
    "notifications": ":material/notifications:",
    "help": ":material/help:",

    # Actions
    "add": ":material/add:",
    "delete": ":material/delete:",
    "edit": ":material/edit:",
    "save": ":material/save:",
    "cancel": ":material/cancel:",
    "refresh": ":material/refresh:",
    "download": ":material/download:",
    "upload": ":material/upload:",
    "search": ":material/search:",
    "sort": ":material/sort:",

    # Status
    "check": ":material/check_circle:",
    "error": ":material/error:",
    "warning": ":material/warning:",
    "info": ":material/info:",
    "pending": ":material/pending:",
    "done": ":material/done:",

    # Content
    "play": ":material/play_circle:",
    "streaming": ":material/subscriptions:",
    "broadcast": ":material/sensors:",
    "live": ":material/live_tv:",

    # People & Users
    "person": ":material/person:",
    "people": ":material/group:",
    "admin": ":material/admin_panel_settings:",

    # Time
    "time": ":material/access_time:",
    "today": ":material/today:",
    "event": ":material/event:",
    "history": ":material/history:",

    # Data
    "stats": ":material/bar_chart:",
    "analytics": ":material/analytics:",
    "trending": ":material/trending_up:",

    # Communication
    "email": ":material/email:",
    "send": ":material/send:",
    "inbox": ":material/inbox:",

    # Special
    "star": ":material/star:",
    "favorite": ":material/favorite:",
    "bookmark": ":material/bookmark:",
    "lightbulb": ":material/lightbulb:",
    "key": ":material/key:",
    "visibility": ":material/visibility:",
    "visibility_of": ":material/visibility_off:",

    # Promotional & Content Discovery
    "new": ":material/fiber_new:",
    "hot": ":material/whatshot:",
    "fire": ":material/local_fire_department:",
    "rated": ":material/grade:",
    "home": ":material/home:",
    "filter": ":material/filter_list:",
    "arrow_forward": ":material/arrow_forward:",
}

# Popular streaming providers supported by TMDB
STREAMING_PROVIDERS = [
    "Netflix",
    "Amazon Prime Video",
    "Hulu",
    "Disney Plus",
    "Max",
    "Apple TV Plus",
    "Paramount Plus",
    "Peacock",
    "Showtime",
    "Starz",
    "MGM Plus",
    "Crunchyroll",
    "fuboTV",
    "Sling TV",
    "YouTube Premium",
    "Discovery Plus",
    "BritBox",
    "AMC Plus",
    "Shudder",
    "Criterion Channel",
]

DB_PATH = os.getenv("DB_PATH", "shows.db")

# --------------- DB LAYER (Supabase) ---------------
@st.cache_resource
def get_supabase_client() -> Client:
    """Get Supabase client (cached across app reruns)"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("⚠️ Supabase not configured. Please set SUPABASE_URL and SUPABASE_KEY in .env file")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def upsert_show(client: Client, tmdb_id:int, title:str, region:str, on_provider:bool, next_air_date:Optional[str], overview:str, poster_path:Optional[str], provider_name:str):
    """Insert or update a show in the user's watchlist"""
    user_id = get_user_id()

    # Check if show already exists
    existing = client.table("shows")\
        .select("id")\
        .eq("user_id", user_id)\
        .eq("tmdb_id", tmdb_id)\
        .eq("provider_name", provider_name)\
        .execute()

    is_new_show = len(existing.data) == 0

    data = {
        "user_id": user_id,
        "tmdb_id": tmdb_id,
        "title": title,
        "region": region,
        "on_provider": on_provider,
        "next_air_date": next_air_date,
        "overview": overview,
        "poster_path": poster_path,
        "provider_name": provider_name
    }

    # Upsert: insert or update if exists
    client.table("shows").upsert(data, on_conflict="user_id,tmdb_id,provider_name").execute()

    # Create notification for new shows
    if is_new_show:
        status = "available" if on_provider else "unavailable"
        notifications.notify_show_status_change(
            client=client,
            user_id=user_id,
            show_title=title,
            show_id=tmdb_id,
            new_status="added",
            send_email=False
        )

        # Check and update show status from TMDB (series finale/cancellation detection)
        show_status.update_show_status(client, user_id, tmdb_id, title)

def delete_show(client: Client, tmdb_id:int, region:str, provider_name:str):
    """Delete a show from the user's watchlist"""
    client.table("shows")\
        .delete()\
        .eq("user_id", get_user_id())\
        .eq("tmdb_id", tmdb_id)\
        .eq("region", region)\
        .eq("provider_name", provider_name)\
        .execute()

def list_shows(client: Client) -> List[Dict[str, Any]]:
    """Get all shows from the user's watchlist"""
    result = client.table("shows")\
        .select("tmdb_id, title, region, on_provider, provider_name, next_air_date, overview, poster_path, production_status, status_message, status_confidence, in_production, created_at, show_status")\
        .eq("user_id", get_user_id())\
        .order("title")\
        .execute()
    return result.data

# --------------- TMDB API ---------------
def tmdb_get(path:str, params:Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY is not set. Get one free at themoviedb.org and set the environment variable.")
    headers = {"Authorization": f"Bearer {TMDB_API_KEY}"} if len(TMDB_API_KEY) > 40 else {}
    # Support either v3 key (api_key=) or v4 bearer token
    p = dict(params or {})
    if not headers:
        p["api_key"] = TMDB_API_KEY
    url = f"{TMDB_BASE}{path}"
    r = requests.get(url, params=p, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()

def search_tv(query:str) -> List[Dict[str, Any]]:
    data = tmdb_get("/search/tv", {"query": query, "include_adult": "false", "language": "en-US", "page": 1})
    return data.get("results", [])

def tv_details(tv_id:int) -> Dict[str, Any]:
    return tmdb_get(f"/tv/{tv_id}", {"language": "en-US"})

@st.cache_data(ttl=21600, show_spinner=False)
def get_show_seasons(tv_id:int) -> Dict[str, Any]:
    """Cached show details for the episode guide (6h TTL). Real seasons only (skip specials)."""
    try:
        d = tv_details(tv_id)
        return {
            "status": d.get("status"),
            "seasons": [s for s in (d.get("seasons") or []) if s.get("season_number")],
        }
    except Exception:
        return {}

@st.cache_data(ttl=21600, show_spinner=False)
def get_season_episodes(tv_id:int, season_number:int) -> List[Dict[str, Any]]:
    """Cached episode list for one season (6h TTL)."""
    try:
        sf = tmdb_get(f"/tv/{tv_id}/season/{season_number}", {"language": "en-US"})
        return sf.get("episodes") or []
    except Exception:
        return []

@st.cache_data(ttl=21600, show_spinner=False)
def get_next_episode(tv_id:int) -> Optional[Dict[str, Any]]:
    """Cached upcoming-episode info for the countdown: {season, episode, name, air_date} or None."""
    try:
        nxt = tv_details(tv_id).get("next_episode_to_air")
        if isinstance(nxt, dict) and nxt.get("air_date"):
            return {
                "season": nxt.get("season_number"),
                "episode": nxt.get("episode_number"),
                "name": nxt.get("name"),
                "air_date": nxt.get("air_date"),
            }
    except Exception:
        pass
    return None


@st.cache_data(ttl=21600, show_spinner=False)
def get_show_meta(tv_id:int) -> Dict[str, Any]:
    """Cached high-level show metadata for the detail panel (6h TTL)."""
    try:
        d = tv_details(tv_id)
        return {
            "name": d.get("name"),
            "poster_path": d.get("poster_path"),
            "overview": d.get("overview"),
            "status": d.get("status"),
            "number_of_seasons": d.get("number_of_seasons"),
            "number_of_episodes": d.get("number_of_episodes"),
            "first_air_date": d.get("first_air_date"),
            "next_episode_to_air": d.get("next_episode_to_air"),
            "seasons": [s for s in (d.get("seasons") or []) if s.get("season_number")],
        }
    except Exception:
        return {}


@st.cache_data(ttl=21600, show_spinner=False)
def get_related_shows(tv_id:int) -> List[Dict[str, Any]]:
    """Related/recommended shows (TMDB recommendations) — surfaces spin-offs & franchise
    entries, e.g. Game of Thrones → House of the Dragon."""
    try:
        d = tmdb_get(f"/tv/{tv_id}/recommendations", {"language": "en-US", "page": 1})
        out = []
        for s in (d.get("results") or [])[:12]:
            if s.get("id"):
                out.append({"tmdb_id": s["id"],
                            "title": s.get("name") or s.get("original_name") or "",
                            "poster_path": s.get("poster_path"),
                            "overview": s.get("overview") or ""})
        return out
    except Exception:
        return []


@st.cache_data(ttl=86400, show_spinner=False)
def get_tvmaze_episode_data(tv_id:int) -> Dict[Any, Dict[str, str]]:
    """Fallback episode summaries AND still images from TVmaze (free, no key), keyed by
    (season, episode): {(s,n): {'overview': txt, 'image': url}}. Fills gaps where TMDB
    lacks an overview or a still. Maps via the show's IMDb id."""
    import re as _re
    try:
        imdb = (tmdb_get(f"/tv/{tv_id}/external_ids") or {}).get("imdb_id")
        if not imdb:
            return {}
        rr = requests.get("https://api.tvmaze.com/lookup/shows", params={"imdb": imdb}, timeout=15)
        if rr.status_code != 200:
            return {}
        show = rr.json()
        eps = requests.get(f"https://api.tvmaze.com/shows/{show['id']}/episodes", timeout=15).json()
        out = {}
        for e in eps:
            s, n = e.get("season"), e.get("number")
            if not (s and n):
                continue
            txt = _re.sub("<[^>]+>", "", e.get("summary") or "").strip()
            img = (e.get("image") or {}).get("medium") or (e.get("image") or {}).get("original")
            if txt or img:
                out[(s, n)] = {"overview": txt, "image": img}
        return out
    except Exception:
        return {}


def _availability_line(d: Dict[str, Any]) -> str:
    """One-line availability/status summary from show metadata (markdown)."""
    today = dt.date.today()
    status = d.get("status") or ""
    nseasons = d.get("number_of_seasons") or 0
    neps = d.get("number_of_episodes") or 0
    first = d.get("first_air_date") or ""
    nxt = d.get("next_episode_to_air")
    badge = {
        "Returning Series": "📺 Returning", "Ended": "✅ Ended",
        "Canceled": "🚫 Canceled", "In Production": "🎬 In production",
        "Planned": "🗓️ Planned",
    }.get(status, status)
    is_new = False
    if first:
        try:
            if (today - dt.date.fromisoformat(first)).days <= 120 and status in ("Returning Series", "In Production"):
                is_new = True
        except Exception:
            pass
    parts = []
    if is_new:
        parts.append("🆕 **New**")
    if badge:
        parts.append(badge)
    if first:
        parts.append(f"Premiered {first}")
    if nseasons:
        parts.append(f"{nseasons} season" + ("s" if nseasons != 1 else ""))
    if neps:
        parts.append(f"{neps} episode" + ("s" if neps != 1 else ""))
    line = " · ".join(parts)
    if isinstance(nxt, dict) and nxt.get("air_date"):
        ad = nxt["air_date"]
        try:
            days = (dt.date.fromisoformat(ad) - today).days
            when = "today" if days == 0 else (f"in {days} days" if days > 0 else f"{abs(days)} days ago")
            line += f"\n\n⏭️ **Next:** S{nxt.get('season_number')}E{nxt.get('episode_number')} — {ad} ({when})"
        except Exception:
            line += f"\n\n⏭️ **Next:** {ad}"
    elif status in ("Returning Series", "In Production"):
        line += "\n\n⏭️ Next episode date TBA"
    return line


def render_episode_guide(tv_id:int, key_prefix:str, client=None, user_id=None, overview=None) -> None:
    """Rich detail panel: summary + availability + season 'bricks' + episode guide.
    Tap a season brick to load that season's episodes (with watched tracking when available)."""
    meta = get_show_meta(tv_id)
    ov = (meta.get("overview") or overview or "").strip()
    if ov:
        st.markdown(ov)
    if meta:
        st.caption(_availability_line(meta))
    seasons = meta.get("seasons") or []
    if not seasons:
        st.caption("No season data available from TMDB.")
        return
    labels = {s["season_number"]: (s.get("name") or f"Season {s['season_number']}") for s in seasons}
    nums = [s["season_number"] for s in seasons]
    sel_key = f"{key_prefix}_selseason"
    if st.session_state.get(sel_key) not in nums:
        st.session_state[sel_key] = nums[-1]   # default to most recent season
    st.markdown("**Seasons** — tap one for its episode guide")
    per_row = 6
    for i in range(0, len(seasons), per_row):
        bcols = st.columns(per_row)
        for j, s in enumerate(seasons[i:i + per_row]):
            n = s["season_number"]
            ecount = s.get("episode_count") or 0
            with bcols[j]:
                is_sel = st.session_state.get(sel_key) == n
                if st.button(f"S{n} · {ecount}ep", key=f"{key_prefix}_brick_{n}",
                             use_container_width=True,
                             type="primary" if is_sel else "secondary"):
                    st.session_state[sel_key] = n
                    st.rerun()
    sel = st.session_state.get(sel_key, nums[-1])
    st.markdown(f"#### {labels.get(sel, f'Season {sel}')}")
    _render_season_episodes(tv_id, sel, key_prefix, client, user_id)


def _render_season_episodes(tv_id:int, sel:int, key_prefix:str, client=None, user_id=None) -> None:
    """Episode list (with optional watched tracking) for one selected season."""
    eps = get_season_episodes(tv_id, sel)
    if not eps:
        st.info(":material/info: No episode-level data for this season yet. "
                "(Common for **live sports** and some unscripted titles — the databases don't catalogue individual games/episodes.)")
        return

    # Enrich from TVmaze (cached per show) when TMDB is missing an overview or a still image
    _need_tvmaze = any((not (e.get("overview") or "").strip()) or (not e.get("still_path")) for e in eps)
    _tvmaze = get_tvmaze_episode_data(tv_id) if _need_tvmaze else {}

    today = dt.date.today()
    track = bool(client is not None and user_id and watched.table_available(client))
    wset = watched.get_watched(client, user_id, tv_id) if track else set()

    if track:
        aired = [e for e in eps if (e.get("air_date") and e["air_date"] <= today.isoformat())]
        seen = sum(1 for e in aired if (sel, e.get("episode_number")) in wset)
        st.caption(f"✓ Watched {seen}/{len(aired)} aired this season")
        if aired:
            st.progress(seen / len(aired))
            bc = st.columns(2)
            aired_nums = [e.get("episode_number") for e in aired]
            if bc[0].button("✓ Mark season watched", key=f"{key_prefix}_markall_{sel}",
                            use_container_width=True):
                watched.set_season(client, user_id, tv_id, sel, aired_nums, True)
                st.rerun()
            if bc[1].button("Clear season", key=f"{key_prefix}_clearall_{sel}",
                            use_container_width=True):
                watched.set_season(client, user_id, tv_id, sel, aired_nums, False)
                st.rerun()

    for ep in eps:
        en = ep.get("episode_number") or 0
        name = ep.get("name") or f"Episode {en}"
        ad = ep.get("air_date") or "TBA"
        rating = ep.get("vote_average") or 0
        still = ep.get("still_path")
        upcoming = False
        try:
            if ad != "TBA":
                upcoming = dt.date.fromisoformat(ad) > today
        except Exception:
            pass
        _tvm = _tvmaze.get((sel, en)) if _tvmaze else None
        # still: TMDB first, else TVmaze image
        still_url = (f"https://image.tmdb.org/t/p/w185{still}" if still
                     else (_tvm.get("image") if _tvm else None))
        # layout: still | info | date | (watched)
        ec = st.columns([1.3, 4, 1, 0.8]) if track else st.columns([1.3, 4, 1])
        with ec[0]:
            if still_url:
                st.image(still_url, use_column_width=True)
        with ec[1]:
            st.markdown(f"**E{en:02d} · {name}**" + ("  🔜" if upcoming else ""))
            ov = (ep.get("overview") or "").strip() or ((_tvm.get("overview") if _tvm else "") or "")
            if ov:
                st.write(ov)   # readable body text (was a tiny grey caption)
        with ec[2]:
            st.caption(f"📅 {ad}")
            if rating:
                st.caption(f"⭐ {rating:.1f}")
        if track:
            with ec[3]:
                if upcoming:
                    st.caption(" ")
                else:
                    is_watched = (sel, en) in wset
                    new_val = st.checkbox("✓", value=is_watched,
                                          key=f"{key_prefix}_w_{sel}_{en}",
                                          help="Mark watched")
                    if new_val != is_watched:
                        watched.set_watched(client, user_id, tv_id, sel, en, new_val)
                        st.rerun()
        st.markdown("<hr style='margin:2px 0;opacity:0.15'>", unsafe_allow_html=True)

def render_show_row(r, view_mode, client, wcounts):
    """Render one watchlist show card (grid or list) + its episode-guide expander."""
    provider_name = r.get("provider_name", DEFAULT_PROVIDER)
    display_provider_name = normalize_provider_name(provider_name)
    next_air_date = r.get("next_air_date")
    poster_path = r.get("poster_path")

    if view_mode == 'grid':
        cols = st.columns([2, 4, 3, 2])
        with cols[0]:
            if poster_path:
                st.image(f"https://image.tmdb.org/t/p/w342{poster_path}", use_column_width=True)
            else:
                st.write(ICONS["movie"])
        with cols[1]:
            title_cols = st.columns([1, 10])
            with title_cols[0]:
                logo_url = get_provider_logo_url(display_provider_name)
                if logo_url:
                    st.image(logo_url, width=48)
            with title_cols[1]:
                st.markdown(f"**{r['title']}**")
            status_icon = f"{ICONS['check']}" if r['on_provider'] else ICONS["pending"]
            st.caption(f"{status_icon} {display_provider_name} • {r['region']}")
            _wc = wcounts.get(r["tmdb_id"], 0)
            if _wc:
                st.caption(f"✓ {_wc} watched")
        with cols[2]:
            if next_air_date:
                try:
                    air_date = dt.date.fromisoformat(next_air_date)
                    days = (air_date - dt.date.today()).days
                    ep_label = ""
                    if days >= 0:
                        ne = get_next_episode(r["tmdb_id"])
                        if ne and ne.get("season") and ne.get("episode"):
                            ep_label = f"S{ne['season']}E{ne['episode']}"
                    if days == 0:
                        st.markdown("🔴 **TODAY**" + (f" · {ep_label}" if ep_label else ""))
                    elif days > 0:
                        st.markdown(f"📅 **Next: {ep_label}**" if ep_label else f"📅 **{next_air_date}**")
                        st.caption(f"⏰ {next_air_date} · in {days} day{'s' if days != 1 else ''}")
                    else:
                        st.markdown(f"📅 {next_air_date}")
                        st.caption(f"({abs(days)} day{'s' if abs(days) != 1 else ''} ago)")
                except Exception:
                    st.caption(f"📅 {next_air_date}")
            else:
                production_status = r.get('production_status')
                status_message = r.get('status_message')
                if production_status:
                    st.markdown(f"**{production_status}**")
                    if status_message:
                        st.caption(status_message)
                elif r['on_provider']:
                    st.markdown("✨ **All Episodes**")
                    st.caption("Series complete")
                else:
                    st.caption("❓ No air date")
        with cols[3]:
            if st.button(ICONS["delete"], key=f"del_{r['tmdb_id']}_{provider_name}", help="Remove", use_container_width=True):
                delete_show(client, r["tmdb_id"], r["region"], provider_name)
                st.rerun()
    else:
        cols = st.columns([1, 4, 2, 2, 1])
        with cols[0]:
            if poster_path:
                st.image(f"https://image.tmdb.org/t/p/w185{poster_path}", width=92)
            else:
                st.write(ICONS["movie"])
        with cols[1]:
            st.markdown(f"**{r['title']}**")
        with cols[2]:
            service_cols = st.columns([1, 3])
            with service_cols[0]:
                logo_url = get_provider_logo_url(display_provider_name)
                if logo_url:
                    st.image(logo_url, width=32)
            with service_cols[1]:
                status_icon = f"{ICONS['check']}" if r['on_provider'] else ICONS["pending"]
                st.caption(f"{status_icon} {display_provider_name}")
        with cols[3]:
            if next_air_date:
                try:
                    air_date = dt.date.fromisoformat(next_air_date)
                    days = (air_date - dt.date.today()).days
                    ep_label = ""
                    if days >= 0:
                        ne = get_next_episode(r["tmdb_id"])
                        if ne and ne.get("season") and ne.get("episode"):
                            ep_label = f"S{ne['season']}E{ne['episode']} · "
                    if days == 0:
                        st.markdown(f"🔴 **TODAY** {ep_label}".strip())
                    elif days > 0:
                        st.caption(f"📅 {ep_label}in {days}d")
                    else:
                        st.caption(f"📅 {next_air_date}")
                except Exception:
                    st.caption(f"📅 {next_air_date}")
            else:
                production_status = r.get('production_status')
                if production_status:
                    st.caption(f"{production_status}")
                else:
                    st.caption("❓")
        with cols[4]:
            if st.button(ICONS["delete"], key=f"del_list_{r['tmdb_id']}_{provider_name}", help="Remove", use_container_width=True):
                delete_show(client, r["tmdb_id"], r["region"], provider_name)
                st.rerun()

    # Show Details — summary + availability + season bricks + episode guide; lazy-loaded.
    eg_key = f"eg_{r['tmdb_id']}_{provider_name}"
    if st.session_state.get(eg_key):
        if st.button(":material/menu_book: Hide Details", key=f"{eg_key}_btn", use_container_width=True):
            st.session_state[eg_key] = False
            st.rerun()
        render_episode_guide(r["tmdb_id"], eg_key, client, get_user_id(), overview=r.get("overview"))
    else:
        if st.button(":material/menu_book: Show Details & Episodes", key=f"{eg_key}_btn", use_container_width=True):
            st.session_state[eg_key] = True
            st.rerun()
    st.divider()


def _current_season(meta: Dict[str, Any]):
    """Best guess at the 'current' (now-airing or most-recently-aired) season number."""
    seasons = meta.get("seasons") or []
    if not seasons:
        return None
    nxt = meta.get("next_episode_to_air")
    if isinstance(nxt, dict) and nxt.get("season_number"):
        return nxt["season_number"]
    today = dt.date.today().isoformat()
    aired = [s for s in seasons if (s.get("air_date") or "0000") <= today and (s.get("episode_count") or 0) > 0]
    if aired:
        return max(s["season_number"] for s in aired)
    return seasons[-1]["season_number"]


def open_show_page(show: Dict[str, Any]) -> None:
    """on_click callback: open the PDP via a ?show=<id> query param. Runs BEFORE the
    rerun, so the router (top of script) sees the new param on the first pass — single
    click, no race. Creates a real history entry (browser Back returns to the list) and
    is bookmarkable; still an in-app rerun (no reload → login preserved)."""
    sid = show.get("tmdb_id")
    st.session_state.setdefault("_showcache", {})[sid] = show
    st.query_params["show"] = str(sid)


def close_show_page() -> None:
    """on_click callback: return to the list by clearing the ?show param."""
    st.query_params.clear()


def _wl_add(client, tid, title, region, on_prov, next_air, overview, poster_path, provider_name) -> None:
    """on_click callback: add a show (for a specific service) to the watchlist. Values are
    passed via args= (bound per-widget), so the right show is added even though the buttons
    are created in a loop. No clear_search → the search/grow results stay in place."""
    upsert_show(client, tid, title, region, on_prov, next_air, overview, poster_path, provider_name)


_OPENSEQ = [0]  # reset to 0 every Streamlit rerun (whole script re-executes)


def clickable_title(title: str, show: Dict[str, Any]) -> None:
    """Render a show title as a full-width button that opens its detail page (PDP).
    The per-run sequence makes the key unique even if the same show appears in
    several tabs (New/Trending/Top) in the same render."""
    _OPENSEQ[0] += 1
    st.button(title, key=f"open_{show.get('tmdb_id')}_{_OPENSEQ[0]}",
              use_container_width=True, help="Open show details",
              on_click=open_show_page, args=(show,))


def _poster_src(poster_path):
    """Full image URL for a poster_path — passes through real URLs (sports team logos)
    and prefixes the TMDB CDN for TMDB paths."""
    if not poster_path:
        return None
    p = str(poster_path)
    return p if p.startswith("http") else f"https://image.tmdb.org/t/p/w342{p}"


def clickable_poster(tmdb_id, poster_path) -> None:
    """Render a poster with an invisible Streamlit button overlaid on top (see the
    .sgposter CSS). Clicking the poster opens the detail page via an in-app rerun —
    NOT a full-page reload, which would drop the login session."""
    _OPENSEQ[0] += 1
    src = _poster_src(poster_path)
    if src:
        _fit = "contain" if str(poster_path).startswith("http") else "cover"
        st.markdown(f'<img class="sgposter" style="object-fit:{_fit}" src="{src}">',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="sgposter sgph">📺</div>', unsafe_allow_html=True)
    st.button("View details", key=f"pp_{tmdb_id}_{_OPENSEQ[0]}", use_container_width=True,
              on_click=open_show_page, args=({"tmdb_id": tmdb_id, "poster_path": poster_path},))


def render_sports_page(show: Dict[str, Any], client=None, user_id=None) -> None:
    """Detail page for a followed team (NFL/MLB/NBA/NHL) — schedule as 'episodes' (games)."""
    st.button(":material/arrow_back: Back to list", key="pdp_back", on_click=close_show_page)
    league, team_id = sports.decode_id(show.get("tmdb_id"))
    name = show.get("title") or "Team"
    logo = show.get("poster_path")
    games = sports.get_team_schedule(league, team_id) if league else []
    ng = sports.next_game(games)
    w, l, d = sports.record(games, name)

    def _logo_img(u, h=104):
        return f'<img src="{u}" style="height:{h}px;vertical-align:middle;margin:0 8px">' if u else ""

    hc = st.columns([1, 3])
    with hc[0]:
        if logo:
            st.image(logo, use_column_width=True)
    with hc[1]:
        st.markdown(f"## {name}")
        st.markdown(sports.league_label(league)
                    + (f"  ·  **{sports.record_str(league, w, l, d)}**" if (w or l or d) else ""))
        if ng:
            _net = f' · 📺 {ng["network"]}' if ng.get("network") else ""
            st.markdown(
                f'<div style="background:rgba(34,197,94,.12);border-radius:8px;padding:8px 12px;'
                f'display:flex;align-items:center;flex-wrap:wrap">'
                f'🟢&nbsp;<b>Next:</b>{_logo_img(ng.get("away_logo"), 120)}<b>{ng["away"]}</b>'
                f'<span style="opacity:.55;margin:0 5px">@</span>'
                f'{_logo_img(ng.get("home_logo"), 120)}<b>{ng["home"]}</b>'
                f'<span style="opacity:.8">&nbsp;— {ng["date"]}{_net}</span></div>',
                unsafe_allow_html=True)
        if client is not None:
            def _rm():
                delete_show(client, show.get("tmdb_id"), show.get("region") or DEFAULT_REGION,
                            show.get("provider_name", "Sports"))
                st.query_params.clear()
            st.button(":material/delete: Remove from watchlist", key=f"sp_del_{team_id}", on_click=_rm)

    cov = sports.coverage_map_url(league)
    if cov:
        st.caption(f"📍 Regional TV coverage varies by market — check the "
                   f"[506sports coverage maps]({cov}).")
    st.divider()
    if not games:
        st.info("No schedule available right now.")
        return

    def _game_row(g, highlight=False):
        c = st.columns([2, 5, 2])
        with c[0]:
            wk = g.get("week")
            st.markdown(f"**Wk {wk}**" if wk else f"**{g.get('date') or 'TBA'}**")
            if wk:
                st.caption(g.get("date") or "TBA")
        with c[1]:
            score = ""
            if g.get("completed") and g.get("home_score") not in (None, ""):
                score = f' <span style="opacity:.65">— {g.get("away_score")}–{g.get("home_score")}</span>'
            wt = "font-weight:700;" if highlight else ""
            st.markdown(
                f'<div style="{wt}display:flex;align-items:center;flex-wrap:wrap">'
                f'{"🟢 " if highlight else ""}{_logo_img(g.get("away_logo"))}{g.get("away")}'
                f'<span style="opacity:.55;margin:0 6px">@</span>'
                f'{_logo_img(g.get("home_logo"))}{g.get("home")}{score}</div>',
                unsafe_allow_html=True)
            if g.get("network"):
                st.caption(f"📺 {g['network']}")
        with c[2]:
            st.caption(g.get("status") or ("Final" if g.get("completed") else "Scheduled"))
        st.markdown("<hr style='margin:2px 0;opacity:0.15'>", unsafe_allow_html=True)

    today = dt.date.today().isoformat()
    upcoming = [g for g in games if (g.get("date") or "") >= today and not g.get("completed")]
    recent = [g for g in games if g.get("completed")]

    st.markdown(f"### Upcoming games ({len(upcoming)})  ·  🟢 = next")
    for g in upcoming[:25]:
        _game_row(g, highlight=bool(ng and g.get("datetime") == ng.get("datetime")))
    if len(upcoming) > 25:
        st.caption(f"…and {len(upcoming) - 25} more this season")
    if recent:
        with st.expander(f"Recent results ({len(recent)})"):
            for g in reversed(recent[-15:]):
                _game_row(g)


def render_show_page(show: Dict[str, Any], client=None, user_id=None) -> None:
    """Full-page show detail (PDP): poster + summary + availability + ALL seasons
    (current season highlighted 🟢) + episode guide. Reached by clicking a show card."""
    tmdb_id = show.get("tmdb_id")
    if sports.is_sports_id(tmdb_id):
        render_sports_page(show, client, user_id)
        return
    st.button(":material/arrow_back: Back to list", key="pdp_back", on_click=close_show_page)

    meta = get_show_meta(tmdb_id) or {}
    title = show.get("title") or meta.get("name") or "Show"
    cur = _current_season(meta)

    hc = st.columns([1, 2.5])
    with hc[0]:
        pp = show.get("poster_path") or meta.get("poster_path")
        if pp:
            st.image(f"https://image.tmdb.org/t/p/w342{pp}", use_column_width=True)
        else:
            st.write(ICONS["movie"])
    with hc[1]:
        st.markdown(f"## {title}")
        if meta:
            st.markdown(_availability_line(meta))
        if cur is not None:
            st.success(f"🟢 Current season: **Season {cur}**")
        # Watchlist membership → offer Remove (if present) or Add (if not)
        wl_row = None
        if client is not None:
            try:
                _rr = (client.table("shows").select("tmdb_id,region,provider_name")
                       .eq("user_id", user_id).eq("tmdb_id", tmdb_id).limit(1).execute())
                if _rr.data:
                    wl_row = _rr.data[0]
            except Exception:
                wl_row = None
        if wl_row is not None:
            st.caption("✓ On your watchlist")
            def _pdp_remove():
                delete_show(client, tmdb_id, wl_row.get("region") or DEFAULT_REGION,
                            wl_row.get("provider_name", DEFAULT_PROVIDER))
                st.query_params.clear()   # back to the list after removing
            st.button(":material/delete: Remove from watchlist", key=f"pdp_del_{tmdb_id}", on_click=_pdp_remove)
        elif client is not None:
            def _pdp_add():
                _nxt = meta.get("next_episode_to_air")
                _nad = _nxt.get("air_date") if isinstance(_nxt, dict) else None
                upsert_show(client, tmdb_id, title, DEFAULT_REGION, True, _nad,
                            (meta.get("overview") or show.get("overview") or ""),
                            show.get("poster_path"), "Multiple Providers")
            st.button(":material/add: Add to watchlist", key=f"pdp_add_{tmdb_id}", type="primary", on_click=_pdp_add)

    ov = (meta.get("overview") or show.get("overview") or "").strip()
    if ov:
        st.markdown(ov)

    st.divider()
    seasons = meta.get("seasons") or []
    if not seasons:
        st.info("No season data available from TMDB.")
        return
    labels = {s["season_number"]: (s.get("name") or f"Season {s['season_number']}") for s in seasons}
    nums = [s["season_number"] for s in seasons]
    sel_key = f"pdp_season_{tmdb_id}"
    if st.session_state.get(sel_key) not in nums:
        st.session_state[sel_key] = cur if cur in nums else nums[-1]

    st.markdown("### Seasons  ·  🟢 = current  ·  blue bar = your watch progress")
    # Watched-episode counts per season → the per-brick progress bars (resume helper)
    track = bool(client is not None and user_id and watched.table_available(client))
    watched_by_season: Dict[int, int] = {}
    if track:
        try:
            for (sn, en) in watched.get_watched(client, user_id, tmdb_id):
                watched_by_season[sn] = watched_by_season.get(sn, 0) + 1
        except Exception:
            watched_by_season = {}
    per_row = 6
    for i in range(0, len(seasons), per_row):
        bcols = st.columns(per_row)
        for j, s in enumerate(seasons[i:i + per_row]):
            n = s["season_number"]
            ec = s.get("episode_count") or 0
            is_sel = st.session_state.get(sel_key) == n
            lab = ("🟢 " if n == cur else "") + f"S{n} · {ec}ep"
            with bcols[j]:
                if st.button(lab, key=f"{sel_key}_b_{n}", use_container_width=True,
                             type="primary" if is_sel else "secondary"):
                    st.session_state[sel_key] = n
                    st.rerun()
                if track:
                    wn = min(watched_by_season.get(n, 0), ec) if ec else 0
                    pct = int(round(100 * wn / ec)) if ec else 0
                    done = bool(ec and wn >= ec)
                    cap = "—" if not ec else (("✓ " if done else "") + f"{wn}/{ec}")
                    st.markdown(
                        f'<div style="background:#e9e9e9;border-radius:4px;height:7px;margin-top:2px;overflow:hidden">'
                        f'<div style="width:{pct}%;background:#1c83e1;height:100%"></div></div>'
                        f'<div style="font-size:0.66rem;color:#888;text-align:center;line-height:1.5">{cap}</div>',
                        unsafe_allow_html=True)

    sel = st.session_state.get(sel_key, nums[-1])
    head = f"#### {labels.get(sel, f'Season {sel}')}"
    if sel == cur:
        head += "  🟢 *Current*"
    st.markdown(head)
    _render_season_episodes(tmdb_id, sel, f"pdp_{tmdb_id}", client, user_id)

    # Related shows & spin-offs — quick-add multiple from one place
    related = get_related_shows(tmdb_id)
    if related:
        st.divider()
        st.markdown("### :material/hub: Related shows & spin-offs")
        st.caption("Tap a poster to open it, or ➕ to add it to your watchlist.")
        owned_ids = set()
        if client is not None:
            try:
                owned_ids = {x["tmdb_id"] for x in
                             (client.table("shows").select("tmdb_id").eq("user_id", user_id).execute().data or [])}
            except Exception:
                owned_ids = set()
        per_row = 6
        for i in range(0, len(related), per_row):
            rcols = st.columns(per_row)
            for j, rs in enumerate(related[i:i + per_row]):
                with rcols[j]:
                    clickable_poster(rs["tmdb_id"], rs["poster_path"])
                    st.caption(rs["title"])
                    if rs["tmdb_id"] in owned_ids:
                        st.markdown(":blue[✓ In your list]")
                    else:
                        def _add_related(_rs=rs):
                            upsert_show(client, _rs["tmdb_id"], _rs["title"], DEFAULT_REGION, True, None,
                                        _rs.get("overview", ""), _rs.get("poster_path"), "Multiple Providers")
                        st.button(":material/add: Add", key=f"rel_add_{tmdb_id}_{rs['tmdb_id']}",
                                  use_container_width=True, on_click=_add_related)


def render_grid_gallery(rows, client, wcounts, per_row=5):
    """True poster-tile gallery for the grid view (vs. the detailed list rows).
    Each card's title is a button that opens the full show-detail page (PDP)."""
    today = dt.date.today()
    for i in range(0, len(rows), per_row):
        cols = st.columns(per_row)
        for j, r in enumerate(rows[i:i + per_row]):
            with cols[j]:
                clickable_poster(r['tmdb_id'], r.get("poster_path"))
                st.button(r['title'], key=f"open_{r['tmdb_id']}_{r.get('provider_name')}",
                          use_container_width=True, help="Open show details",
                          on_click=open_show_page, args=(r,))
                nad = r.get("next_air_date")
                shown = False
                if nad:
                    try:
                        days = (dt.date.fromisoformat(nad) - today).days
                        if days >= 0:
                            ne = get_next_episode(r["tmdb_id"])
                            ep = f"S{ne['season']}E{ne['episode']} · " if ne and ne.get("season") else ""
                            st.caption(f"📅 {ep}{'TODAY' if days == 0 else f'in {days}d'}")
                            shown = True
                    except Exception:
                        pass
                if not shown:
                    st.caption(r.get("production_status") or "—")
                wc = wcounts.get(r["tmdb_id"], 0)
                if wc:
                    st.caption(f"✓ {wc} watched")
                if st.button(ICONS["delete"], key=f"gdel_{r['tmdb_id']}_{r.get('provider_name')}",
                             help="Remove", use_container_width=True):
                    delete_show(client, r["tmdb_id"], r["region"], r.get("provider_name", DEFAULT_PROVIDER))
                    st.rerun()


def render_upcoming(rows, as_tab=False):
    """Agenda of upcoming episodes across the whole watchlist, grouped by timeframe.

    as_tab=True renders the list directly (for the dedicated Upcoming tab) with an
    empty-state message; otherwise it renders inside a collapsible expander.
    """
    today = dt.date.today()
    up = []
    for r in rows:
        ad = r.get("next_air_date")
        if not ad:
            continue
        try:
            d = dt.date.fromisoformat(ad)
        except Exception:
            continue
        if d >= today:
            up.append((d, r))
    if not up:
        if as_tab:
            st.info("No upcoming episodes scheduled for your watchlist yet. Add shows from the Search tab to see what's coming up.")
        return
    up.sort(key=lambda x: x[0])
    soon = any((d - today).days <= 7 for d, _ in up)

    def _body():
        groups = [
            ("⏰ This week", [x for x in up if (x[0] - today).days <= 7]),
            ("📅 This month", [x for x in up if 7 < (x[0] - today).days <= 30]),
            ("🔜 Later", [x for x in up if (x[0] - today).days > 30]),
        ]
        for label, items in groups:
            if not items:
                continue
            st.markdown(f"**{label}**")
            for d, r in items:
                days = (d - today).days
                ne = get_next_episode(r["tmdb_id"])
                ep = f"S{ne['season']}E{ne['episode']}" if ne and ne.get("season") else ""
                c = st.columns([1, 4])
                with c[0]:
                    clickable_poster(r['tmdb_id'], r.get("poster_path"))
                with c[1]:
                    when = "🔴 TODAY" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
                    clickable_title(r['title'], r)
                    st.caption(f"📅 {d.isoformat()} · {when}" + (f" · {ep}" if ep else ""))

    if as_tab:
        st.subheader(f"📅 Upcoming Episodes ({len(up)})")
        _body()
    else:
        with st.expander(f"📅 Upcoming Episodes ({len(up)})", expanded=soon):
            _body()


def tv_watch_providers(tv_id:int) -> Dict[str, Any]:
    return tmdb_get(f"/tv/{tv_id}/watch/providers")

def is_on_provider_in_region(providers_payload:Dict[str, Any], provider_name:str, region:str) -> bool:
    region_block = providers_payload.get("results", {}).get(region.upper())
    if not region_block:
        return False
    # Check any access type (flatrate, buy, rent, ads, free) that contains the provider_name
    for key in ("flatrate", "rent", "buy", "ads", "free"):
        for item in region_block.get(key, []) or []:
            if item.get("provider_name","").lower() == provider_name.lower():
                return True
    return False

def get_all_providers_in_region(providers_payload:Dict[str, Any], region:str) -> Dict[str, List[str]]:
    """Get all available providers for a show in a specific region, organized by access type."""
    region_block = providers_payload.get("results", {}).get(region.upper())
    if not region_block:
        return {}

    providers_by_type = {}
    for access_type in ("flatrate", "rent", "buy", "ads", "free"):
        providers = region_block.get(access_type, []) or []
        if providers:
            providers_by_type[access_type] = [p.get("provider_name", "Unknown") for p in providers]

    return providers_by_type

def discover_next_air_date(details:Dict[str, Any]) -> Optional[str]:
    # Prefer TMDB's next_episode_to_air field if available
    nxt = details.get("next_episode_to_air")
    if isinstance(nxt, dict) and nxt.get("air_date"):
        return nxt["air_date"]
    # Fallback: check upcoming season episodes (rough heuristic)
    # Inspect last and next seasons for any episodes with air_date >= today
    today = dt.date.today()
    for season in details.get("seasons", []) or []:
        season_number = season.get("season_number")
        if season_number is None:
            continue
        try:
            season_full = tmdb_get(f"/tv/{details['id']}/season/{season_number}", {"language":"en-US"})
        except Exception:
            continue
        for ep in (season_full.get("episodes") or []):
            try:
                ad = ep.get("air_date")
                if ad:
                    d = dt.date.fromisoformat(ad)
                    if d >= today:
                        return ad
            except Exception:
                pass
    return None

def refresh_stale_air_dates(client: Client, shows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Check for stale next_air_date values (in the past) and refresh them from TMDB.
    Updates database and returns updated show list.
    """
    today = dt.date.today()
    updated_shows = []

    for show in shows:
        # Sports-team rows (negative ids) aren't TMDB shows — leave their game date as-is
        if (show.get("tmdb_id") or 0) < 0:
            updated_shows.append(show)
            continue
        next_air_date = show.get("next_air_date")
        needs_refresh = False

        # Check if date is in the past
        if next_air_date:
            try:
                air_date = dt.date.fromisoformat(next_air_date)
                if air_date < today:
                    needs_refresh = True
            except Exception:
                needs_refresh = True  # Invalid date format, refresh it

        # Refresh from TMDB if needed
        if needs_refresh:
            try:
                details = tv_details(show["tmdb_id"])
                new_next_air = discover_next_air_date(details)

                # Update in database
                client.table("shows")\
                    .update({"next_air_date": new_next_air})\
                    .eq("user_id", get_user_id())\
                    .eq("tmdb_id", show["tmdb_id"])\
                    .eq("region", show["region"])\
                    .eq("provider_name", show.get("provider_name", "Netflix"))\
                    .execute()

                # Update in the current list
                show["next_air_date"] = new_next_air
            except Exception as e:
                # Silently fail - keep existing data
                pass

        updated_shows.append(show)

    return updated_shows

# --------------- PROMOTIONAL CONTENT ---------------
def get_new_shows(region: str = "US", limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get TV shows that premiered in the last 30 days.
    Returns shows with air dates and available on streaming in the region.
    """
    try:
        today = dt.date.today()
        thirty_days_ago = today - dt.timedelta(days=30)

        # Use TMDB discover to find recently premiered shows
        params = {
            "api_key": TMDB_API_KEY,
            "language": "en-US",
            "sort_by": "popularity.desc",
            "first_air_date.gte": thirty_days_ago.isoformat(),
            "first_air_date.lte": today.isoformat(),
            "vote_count.gte": 10,  # Filter out shows with very few votes
            "page": 1
        }

        response = requests.get(f"{TMDB_BASE}/discover/tv", params=params, timeout=10)
        response.raise_for_status()
        results = response.json().get("results", [])

        return results[:limit]
    except Exception as e:
        logger.error(f"Error fetching new shows: {e}")
        return []

def get_coming_soon_shows(region: str = "US", limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get TV shows with announced air dates within the next 180 days.
    Returns shows that are coming soon with specific air dates.
    """
    try:
        today = dt.date.today()
        six_months_from_now = today + dt.timedelta(days=180)

        # Use TMDB discover to find upcoming shows
        params = {
            "api_key": TMDB_API_KEY,
            "language": "en-US",
            "sort_by": "popularity.desc",
            "first_air_date.gte": today.isoformat(),
            "first_air_date.lte": six_months_from_now.isoformat(),
            "vote_count.gte": 5,  # Filter out shows with very few votes
            "page": 1
        }

        response = requests.get(f"{TMDB_BASE}/discover/tv", params=params, timeout=10)
        response.raise_for_status()
        results = response.json().get("results", [])

        return results[:limit]
    except Exception as e:
        logger.error(f"Error fetching coming soon shows: {e}")
        return []

def get_trending_shows(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get trending TV shows this week.
    Returns the most popular and talked-about shows right now.
    """
    try:
        # Use TMDB trending endpoint for weekly trending shows
        params = {
            "api_key": TMDB_API_KEY,
            "language": "en-US"
        }

        response = requests.get(f"{TMDB_BASE}/trending/tv/week", params=params, timeout=10)
        response.raise_for_status()
        results = response.json().get("results", [])

        return results[:limit]
    except Exception as e:
        logger.error(f"Error fetching trending shows: {e}")
        return []

def get_top_rated_shows(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get all-time top rated TV shows.
    Returns critically acclaimed and highest-rated shows on TMDB.
    """
    try:
        # Use TMDB top rated endpoint
        params = {
            "api_key": TMDB_API_KEY,
            "language": "en-US",
            "page": 1
        }

        response = requests.get(f"{TMDB_BASE}/tv/top_rated", params=params, timeout=10)
        response.raise_for_status()
        results = response.json().get("results", [])

        return results[:limit]
    except Exception as e:
        logger.error(f"Error fetching top rated shows: {e}")
        return []

# --------------- LOGO OVERRIDE PERSISTENCE ---------------
def load_logo_overrides(client: Client) -> dict:
    """Load logo URL overrides from Supabase."""
    try:
        result = client.table("logo_overrides").select("*").execute()
        return {row["provider_name"]: row["logo_url"] for row in result.data}
    except Exception as e:
        st.warning(f"Could not load logo overrides: {e}")
        return {}

def save_logo_overrides(client: Client, overrides: dict):
    """Save logo URL overrides to Supabase."""
    try:
        # Upsert each override (insert or update)
        for provider_name, logo_url in overrides.items():
            client.table("logo_overrides").upsert({
                "provider_name": provider_name,
                "logo_url": logo_url
            }, on_conflict="provider_name").execute()
    except Exception as e:
        st.error(f"Could not save logo overrides: {e}")

def load_deleted_providers(client: Client) -> list:
    """Load list of deleted providers from Supabase."""
    try:
        result = client.table("deleted_providers").select("provider_name").execute()
        return [row["provider_name"] for row in result.data]
    except Exception as e:
        st.warning(f"Could not load deleted providers: {e}")
        return []

def save_deleted_providers(client: Client, deleted: list):
    """Save list of deleted providers to Supabase."""
    try:
        # First, clear all existing deleted providers
        client.table("deleted_providers").delete().neq("provider_name", "").execute()

        # Then insert the new list
        if deleted:
            data = [{"provider_name": provider} for provider in deleted]
            client.table("deleted_providers").insert(data).execute()
    except Exception as e:
        st.error(f"Could not save deleted providers: {e}")

def load_user_settings() -> dict:
    """Load user settings from JSON file."""
    if os.path.exists(USER_SETTINGS_FILE):
        try:
            with open(USER_SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            st.warning(f"Could not load user settings: {e}")
            return {}
    return {}

def save_user_settings(settings: dict):
    """Save user settings to JSON file."""
    try:
        with open(USER_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        st.error(f"Could not save user settings: {e}")

# --------------- UI HELPERS ---------------
def get_all_provider_logos() -> dict:
    """Get all provider logo mappings."""
    provider_logos = {
        # Major Streaming Services
        "netflix": "https://images.justwatch.com/icon/207360008/s100/netflix.webp",
        "amazon prime video": "https://images.justwatch.com/icon/322992749/s100/amazonprime.webp",
        "prime video": "https://images.justwatch.com/icon/322992749/s100/amazonprime.webp",
        "hulu": "https://images.justwatch.com/icon/116305230/s100/hulu.webp",
        "disney plus": "https://images.justwatch.com/icon/313118777/s100/disneyplus.webp",
        "disney+": "https://images.justwatch.com/icon/313118777/s100/disneyplus.webp",
        "max": "https://images.justwatch.com/icon/332884837/s100/max.webp",
        "hbo max": "https://images.justwatch.com/icon/332884837/s100/max.webp",
        "paramount plus": "https://images.justwatch.com/icon/242706661/s100/paramountplus.webp",
        "paramount+": "https://images.justwatch.com/icon/242706661/s100/paramountplus.webp",
        "peacock": "https://images.justwatch.com/icon/194173870/s100/peacocktv.webp",
        "peacock premium": "https://images.justwatch.com/icon/194173870/s100/peacocktv.webp",
        "apple tv plus": "https://images.justwatch.com/icon/338253870/s100/appletvplus.webp",
        "apple tv+": "https://images.justwatch.com/icon/338253870/s100/appletvplus.webp",

        # Premium Channels
        "showtime": "https://images.justwatch.com/icon/430999/s100/showtime.webp",
        "starz": "https://images.justwatch.com/icon/301254735/s100/starz.webp",
        "mgm plus": "https://images.justwatch.com/icon/302467394/s100/epix.webp",
        "amc+": "https://images.justwatch.com/icon/277399832/s100/amcplus.webp",
        "bet+": "https://images.justwatch.com/icon/248153957/s100/bet-plus.webp",
        "espn+": "https://images.justwatch.com/icon/147638348/s100/espn-plus.webp",

        # Specialty Streaming
        "crunchyroll": "https://images.justwatch.com/icon/324213205/s100/crunchyroll.webp",
        "shudder": "https://images.justwatch.com/icon/2562359/s100/shudder.webp",
        "acorn tv": "https://images.justwatch.com/icon/151881328/s100/acorntv.webp",
        "sundance now": "https://images.justwatch.com/icon/5676163/s100/sundancenow.webp",
        "criterion channel": "https://images.justwatch.com/icon/308609719/s100/criterionchannel.webp",

        # Discovery/Learning
        "youtube premium": "https://images.justwatch.com/icon/70189310/s100/youtubered.webp",
        "discovery plus": "https://images.justwatch.com/icon/240558410/s100/discoveryplusus.webp",
        "discovery+": "https://images.justwatch.com/icon/240558410/s100/discoveryplusus.webp",

        # Free Ad-Supported
        "tubi": "https://images.justwatch.com/icon/313528601/s100/tubitv.webp",
        "pluto tv": "https://images.justwatch.com/icon/312204955/s100/plutotv.webp",
        "freevee": "https://images.justwatch.com/icon/300557484/s100/freevee.webp",
        "amazon freevee": "https://images.justwatch.com/icon/300557484/s100/freevee.webp",
        "the roku channel": "https://images.justwatch.com/icon/76972041/s100/rokuchannel.webp",
        "roku channel": "https://images.justwatch.com/icon/76972041/s100/rokuchannel.webp",
        "plex": "https://images.justwatch.com/icon/301832745/s100/plex.webp",
        "xumo play": "https://images.justwatch.com/icon/308802886/s100/xumoplay.webp",

        # Live TV / Cable
        "fubotv": "https://images.justwatch.com/icon/316727345/s100/fubotv.webp",
        "fubo tv": "https://images.justwatch.com/icon/316727345/s100/fubotv.webp",
        "sling tv": "https://images.justwatch.com/icon/430998/s100/sling-tv.webp",
        "directv stream": "https://images.justwatch.com/icon/257197350/s100/directv-stream.webp",
        "spectrum on demand": "https://images.justwatch.com/icon/305635208/s100/spectrumondemand.webp",

        # Rental/Purchase
        "fandango at home": "https://images.justwatch.com/icon/322380782/s100/vudu.webp",
        "vudu": "https://images.justwatch.com/icon/322380782/s100/vudu.webp",
        "amazon video": "https://images.justwatch.com/icon/430993/s100/amazon.webp",
        "apple tv": "https://images.justwatch.com/icon/338253243/s100/itunes.webp",
        "google play movies": "https://images.justwatch.com/icon/169478387/s100/play.webp",
        "google play movies & tv": "https://images.justwatch.com/icon/169478387/s100/play.webp",
        "microsoft store": "https://images.justwatch.com/icon/820542/s100/microsoft-store.webp",
    }

    return provider_logos

def get_provider_logo_url(provider_name: str) -> Optional[str]:
    """Get logo URL for a specific streaming provider."""
    provider_lower = provider_name.lower()

    # Initialize logo_overrides in session state if not present
    if 'logo_overrides' not in st.session_state:
        st.session_state.logo_overrides = load_logo_overrides(client)

    # Check for overrides first (from persistent storage)
    if provider_lower in st.session_state.logo_overrides:
        return st.session_state.logo_overrides[provider_lower]

    provider_logos = get_all_provider_logos()

    # Exact match (preferred)
    if provider_lower in provider_logos:
        return provider_logos[provider_lower]

    # Partial match only for longer, specific keys to avoid false matches
    # Only match if key is at least 4 chars and is a clear substring
    sorted_keys = sorted(provider_logos.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if len(key) >= 4 and key in provider_lower:
            return provider_logos[key]

    return None  # No logo available

def normalize_provider_name(provider_name: str) -> str:
    """Normalize provider names to consolidated versions."""
    provider_lower = provider_name.lower()

    # Consolidate Paramount variations
    if "paramount" in provider_lower:
        return "Paramount+"

    # Consolidate Disney variations
    if "disney" in provider_lower:
        return "Disney+"

    # Consolidate Apple TV variations (but not Apple TV+ the service)
    if "apple tv" in provider_lower and "apple tv+" not in provider_lower:
        # Could be "Apple TV", "Apple TV Channels", etc.
        if "channel" in provider_lower or provider_lower.strip() == "apple tv":
            return "Apple TV+"

    # Consolidate Amazon variations
    if "amazon" in provider_lower or "prime video" in provider_lower:
        return "Prime Video"

    # Consolidate Discovery variations
    if "discovery" in provider_lower:
        return "Discovery+"

    # Consolidate Hulu variations (Hulu, Hulu (No Ads), etc.)
    if "hulu" in provider_lower:
        return "Hulu"

    # Consolidate Netflix variations (Netflix, Netflix basic with Ads, etc.)
    if "netflix" in provider_lower:
        return "Netflix"

    # Consolidate Peacock variations (Peacock, Peacock Premium, Peacock Premium Plus, etc.)
    if "peacock" in provider_lower:
        return "Peacock"

    # Consolidate Fandango variations (and legacy Vudu)
    if "fandango" in provider_lower and "free" not in provider_lower:
        return "Fandango At Home"
    if "vudu" in provider_lower:
        return "Fandango At Home"

    # Consolidate Max variations
    if "hbo" in provider_lower and "max" in provider_lower:
        return "Max"
    if provider_lower.strip() == "max":
        return "Max"

    # Consolidate Google Play variations
    if "google play" in provider_lower:
        return "Google Play Movies"

    # Consolidate Microsoft Store variations
    if "microsoft" in provider_lower:
        return "Microsoft Store"

    # Return original if no consolidation needed
    return provider_name

# --------------- EMAIL REMINDERS ---------------
def send_email_reminder(user_email: str, show_title: str, provider_name: str, next_air_date: str, poster_path: Optional[str] = None):
    """Send an email reminder for a show airing today."""
    import mailer
    if not mailer.is_configured():
        st.warning("Email not configured. Set SMTP_HOST/SMTP_USER/SMTP_PASS/EMAIL_FROM.")
        return False

    try:
        # Format the email
        poster_img = ""
        if poster_path:
            poster_img = f'<img src="https://image.tmdb.org/t/p/w300{poster_path}" style="max-width: 200px; border-radius: 8px;" />'

        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #E64002;">🎬 {show_title} airs today!</h2>
                {poster_img}
                <p style="font-size: 16px;">
                    <strong>Streaming on:</strong> {provider_name}<br>
                    <strong>Air Date:</strong> {next_air_date}
                </p>
                <p style="color: #666;">
                    Don't miss the latest episode! Check your streaming service now.
                </p>
                <hr style="border: 1px solid #eee; margin: 20px 0;">
                <p style="font-size: 12px; color: #999;">
                    You're receiving this because you're tracking this show in StreamGenie.<br>
                    Manage your watchlist and preferences in the app.
                </p>
            </body>
        </html>
        """

        return mailer.send_email(
            user_email,
            f'🎬 {show_title} airs today on {provider_name}!',
            html_content,
        )

    except Exception as e:
        st.error(f"Failed to send email: {e}")
        return False

def check_and_send_daily_reminders(user_email: str, client: Client):
    """Check for shows airing today and send email + in-app reminders."""
    if not user_email:
        return 0

    today = dt.date.today().isoformat()
    user_id = get_user_id()

    # Get all shows airing today
    result = client.table("shows")\
        .select("*")\
        .eq("user_id", user_id)\
        .eq("next_air_date", today)\
        .execute()

    shows_today = result.data

    sent_count = 0
    for show in shows_today:
        provider_name = normalize_provider_name(show.get("provider_name", DEFAULT_PROVIDER))

        # Send email reminder
        success = send_email_reminder(
            user_email=user_email,
            show_title=show["title"],
            provider_name=provider_name,
            next_air_date=show["next_air_date"],
            poster_path=show.get("poster_path")
        )

        # Create in-app notification
        notifications.notify_new_episode(
            client=client,
            user_id=user_id,
            show_title=show["title"],
            show_id=show["tmdb_id"],
            air_date=show["next_air_date"],
            send_email=False  # Already sent via send_email_reminder
        )

        if success:
            sent_count += 1

    return sent_count

def format_status(on_provider:bool, next_air_date:Optional[str], provider_name:str) -> str:
    badge = f"{ICONS['check']} On {provider_name}" if on_provider else f"⏳ Not on {provider_name} (in selected region)"
    if next_air_date:
        try:
            d = dt.date.fromisoformat(next_air_date)
            days = (d - dt.date.today()).days
            when = "today" if days == 0 else (f"in {days} days" if days > 0 else f"{abs(days)} days ago")
            return f"{badge} · Next episode: {next_air_date} ({when})"
        except Exception:
            return f"{badge} · Next episode: {next_air_date}"
    return badge

# --------------- STREAMLIT UI ---------------
st.set_page_config(page_title="StreamGenie - Streaming Tracker", page_icon="🍿", layout="wide")

# Initialize Supabase client (needed throughout the app)
client = get_supabase_client()

# Initialize background task scheduler
# This will schedule daily reminders at 8 AM and weekly previews on Sunday at 6 PM
scheduler = scheduled_tasks.init_scheduler(client)

# Initialize authentication
auth.init_auth_session()

# Password-recovery flow: convert the Supabase #fragment token to a query param,
# then show a set-new-password form if we're mid-recovery.
auth.inject_recovery_hash_shim()
if auth.handle_password_recovery(client):
    st.stop()

# ── TEMP test-mode: bypass login and run as jjwoods@gmail.com to speed up testing.
#    Set DEV_LOGIN_BYPASS = False (or remove this block) to re-enable real login. ──
DEV_LOGIN_BYPASS = True
_TEST_USER = {"id": "d10fc919-ec74-42c0-846e-16d763eac844", "email": "jjwoods@gmail.com"}
if DEV_LOGIN_BYPASS and not auth.is_authenticated():
    st.session_state.user = dict(_TEST_USER)
    try:
        auth.ensure_user_record(client, _TEST_USER["id"], _TEST_USER["email"])
    except Exception:
        pass

# Persistent login: if the in-memory session was wiped (phone screen-lock / tab
# reconnect) but a refresh-token cookie exists, restore the session silently.
if not auth.is_authenticated():
    auth.restore_session(client)

# Check if user is authenticated
if not auth.is_authenticated():
    # Show login/signup page
    auth.render_auth_ui(client)
    st.stop()  # Stop execution until user logs in

# User is authenticated - show user menu and continue with app
auth.render_user_menu(client)

# Clickable-poster styling: invisible button overlaid on each poster image so a
# click opens the detail page via an in-app rerun (no page reload → keeps login).
st.markdown("""
<style>
/* Hide the image fullscreen/expand button (serves no purpose here) */
[data-testid="StyledFullScreenButton"]{display:none !important;}
button[title="View fullscreen"]{display:none !important;}
/* Tighten the big default top whitespace so we use the space better */
.block-container{padding-top:2.2rem !important;}
header[data-testid="stHeader"]{height:0;}
/* Punch up the main nav tabs: bigger, bolder, clearer active state */
div[data-testid="stTabs"] > div > div[role="tablist"]{
    gap:0.25rem; border-bottom:2px solid rgba(128,128,128,0.25); margin-bottom:0.4rem;}
div[data-testid="stTabs"] button[role="tab"]{
    padding:0.45rem 1.0rem; border-radius:8px 8px 0 0;}
div[data-testid="stTabs"] button[role="tab"] p{
    font-size:1.06rem; font-weight:700;}
div[data-testid="stTabs"] button[role="tab"]:hover{background:rgba(128,128,128,0.10);}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{background:rgba(28,131,225,0.10);}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] p{color:#1c83e1;}
/* Search tab → far right of the nav bar */
div[data-testid="stTabs"] > div > div[role="tablist"] > button[role="tab"]:last-of-type{margin-left:auto;}
/* Full poster, natural 2:3 aspect (no cropping) */
.sgposter{width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:8px;display:block;cursor:pointer;}
div.sgph{aspect-ratio:2/3;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;font-size:2rem;color:#fff;}
/* Overlay the following button invisibly over the poster. margin-% is relative to
   WIDTH, so -150% = 1.5×width = the 2:3 poster's height; the button uses the same
   aspect-ratio so it covers the poster exactly at any column width. */
[data-testid="stElementContainer"]:has(.sgposter) + [data-testid="stElementContainer"]{margin-top:-150%;position:relative;z-index:3;}
[data-testid="stElementContainer"]:has(.sgposter) + [data-testid="stElementContainer"] button{width:100%;aspect-ratio:2/3;opacity:0;cursor:pointer;}
[data-testid="element-container"]:has(.sgposter) + [data-testid="element-container"]{margin-top:-150%;position:relative;z-index:3;}
[data-testid="element-container"]:has(.sgposter) + [data-testid="element-container"] button{width:100%;aspect-ratio:2/3;opacity:0;cursor:pointer;}
</style>
""", unsafe_allow_html=True)

# Self-heal once per session: ensure this auth user has a public.users row
# (FK parent for shows/notifications). Covers dashboard-created or restore-orphaned users.
if not st.session_state.get('_user_record_ensured'):
    _cu = auth.get_current_user()
    if _cu:
        auth.ensure_user_record(client, _cu.get('id'), _cu.get('email'))
        st.session_state['_user_record_ensured'] = True

# Show notifications in sidebar
notifications.render_notifications_ui(client, get_user_id())

# Hero Banner with Netflix-style gradient
st.markdown("""
<style>
.hero-banner {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 25%, #f093fb 50%, #f5576c 75%, #ffa500 100%);
    padding: 3rem 2rem;
    border-radius: 15px;
    margin-bottom: 2rem;
    box-shadow: 0 10px 40px rgba(0,0,0,0.3);
    position: relative;
    overflow: hidden;
}

.hero-banner::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(45deg, rgba(255,255,255,0.1) 25%, transparent 25%, transparent 50%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.1) 75%, transparent 75%, transparent);
    background-size: 50px 50px;
    opacity: 0.3;
    animation: slide 20s linear infinite;
}

@keyframes slide {
    0% { background-position: 0 0; }
    100% { background-position: 50px 50px; }
}

.hero-content {
    position: relative;
    z-index: 1;
    text-align: center;
    color: white;
}

.hero-title {
    font-size: 3rem;
    font-weight: 800;
    margin-bottom: 0.5rem;
    text-shadow: 2px 2px 8px rgba(0,0,0,0.3);
    letter-spacing: -1px;
}

.hero-subtitle {
    font-size: 1.2rem;
    opacity: 0.95;
    font-weight: 300;
    text-shadow: 1px 1px 4px rgba(0,0,0,0.3);
}

.hero-stats {
    margin-top: 1.5rem;
    display: flex;
    justify-content: center;
    gap: 2rem;
    flex-wrap: wrap;
}

.stat-item {
    background: rgba(255,255,255,0.2);
    padding: 0.75rem 1.5rem;
    border-radius: 25px;
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255,255,255,0.3);
}

.stat-number {
    font-size: 1.5rem;
    font-weight: 700;
}

.stat-label {
    font-size: 0.875rem;
    opacity: 0.9;
    margin-top: 0.25rem;
}
</style>

<div class="hero-banner">
    <div class="hero-content">
        <div class="hero-title">🎬 StreamGenie</div>
        <div class="hero-subtitle">Your personal TV show tracker • Never miss an episode again</div>
    </div>
</div>
""", unsafe_allow_html=True)

# Settings toggle (top right corner)
col_spacer, col_gear = st.columns([9, 1])
with col_spacer:
    st.write("")  # Spacing
with col_gear:
    st.write("")  # Spacing
    show_settings = st.toggle(ICONS['settings'], value=False, help="Show/hide settings")

# Collapsible settings section
if show_settings:
    with st.container(border=True):
        st.markdown("""
        <style>
        [data-testid="stVerticalBlock"] > [style*="flex-direction: column;"] > [data-testid="stVerticalBlock"] {
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
        }
        </style>
        """, unsafe_allow_html=True)
        st.markdown(f"### {ICONS['settings']} Settings")
        col1, col2 = st.columns(2)
        with col1:
            region = st.text_input("Region (ISO-3166-1 code)", value=DEFAULT_REGION, help="e.g., US, CA, GB, AU")
        with col2:
            st.write("")
            st.caption(f"TMDB API: {ICONS['check'] if bool(TMDB_API_KEY) else ICONS['error']} {'Connected' if bool(TMDB_API_KEY) else 'Not set'}")
            st.caption(f"Database: {DB_PATH}")

        # Tabs for settings sections
        # Check if user is admin to show Maintenance tab
        user_id = get_user_id()
        user_is_admin = auth.is_admin(client, user_id)

        if user_is_admin:
            tab1, tab2, tab5, tab3, tab4 = st.tabs([f"{ICONS['info']} How It Works", f"{ICONS['settings']} Maintenance", "⏳ Leaving Soon", f"{ICONS['email']} Email Reminders", f"{ICONS['notifications']} Notification Preferences"])
            with tab5:
                leaving_soon.render_admin_panel(client)
        else:
            tab1, tab3, tab4 = st.tabs([f"{ICONS['info']} How It Works", f"{ICONS['email']} Email Reminders", f"{ICONS['notifications']} Notification Preferences"])

        with tab1:
            st.caption("1. Search for any TV show")
            st.caption("2. View ALL available streaming services in your region")
            st.caption("3. Select which service(s) to track")
            st.caption("4. Monitor availability and upcoming episode dates")

        with tab3:
            st.markdown("**Email Reminder Settings**")
            st.caption("Get daily email notifications when your tracked shows air")

            # Load current settings
            if 'user_settings' not in st.session_state:
                st.session_state.user_settings = load_user_settings()

            col_email1, col_email2 = st.columns([3, 1])

            with col_email1:
                user_email = st.text_input(
                    "Your Email",
                    value=st.session_state.user_settings.get('email', ''),
                    placeholder="your@email.com",
                    help="Enter your email to receive daily reminders"
                )

            with col_email2:
                st.write("")
                st.write("")
                reminders_enabled = st.checkbox(
                    "Enable",
                    value=st.session_state.user_settings.get('reminders_enabled', False),
                    help="Enable/disable email reminders"
                )

            # Save button
            col_save, col_test, col_spacer = st.columns([1, 1, 2])
            with col_save:
                if st.button("💾 Save Settings", use_container_width=True):
                    st.session_state.user_settings['email'] = user_email
                    st.session_state.user_settings['reminders_enabled'] = reminders_enabled
                    save_user_settings(st.session_state.user_settings)
                    st.success(f"{ICONS['check']} Settings saved!")

            with col_test:
                if st.button("📧 Test Email", use_container_width=True, disabled=not user_email):
                    import mailer
                    if not mailer.is_configured():
                        st.error(f"{ICONS['error']} Email not configured. Set SMTP_HOST/SMTP_USER/SMTP_PASS/EMAIL_FROM (Postmark/Gmail).")
                    else:
                        # Send a test email
                        success = send_email_reminder(
                            user_email=user_email,
                            show_title="Test Show",
                            provider_name="Netflix",
                            next_air_date=dt.date.today().isoformat(),
                            poster_path=None
                        )
                        if success:
                            st.success(f"{ICONS['check']} Test email sent! Check your inbox.")
                        else:
                            st.error(f"{ICONS['error']} Failed to send test email. Check your configuration.")

            st.write("---")

            # Status display
            st.markdown("**Current Status**")
            st.caption(f"{ICONS['email']} Email: {user_email or 'Not set'}")
            reminders_status = f"{ICONS['check']} Enabled" if reminders_enabled and user_email else f"{ICONS['error']} Disabled"
            st.caption(f"{ICONS['notifications']} Reminders: {reminders_status}")
            import mailer as _mailer
            _email_ok = _mailer.is_configured()
            api_status = f"{ICONS['check']} Configured" if _email_ok else f"{ICONS['error']} Not set"
            st.caption(f"{ICONS['key']} Email (SMTP): {api_status}")

            if _email_ok and reminders_enabled and user_email:
                st.info("📬 You'll receive emails at 8:00 AM when shows air!")
            elif not _email_ok:
                st.warning("⚠️ To enable reminders, set SMTP_HOST/SMTP_USER/SMTP_PASS/EMAIL_FROM (e.g. Postmark or Gmail).")

        if user_is_admin:
            with tab2:
                st.markdown("**Provider Logo Assignments**")

                # Get all logo assignments
                all_logos = get_all_provider_logos()

                # Initialize session state
                if 'logo_overrides' not in st.session_state:
                    st.session_state.logo_overrides = load_logo_overrides(client)

                if 'deleted_providers' not in st.session_state:
                    st.session_state.deleted_providers = load_deleted_providers(client)

                # Filter out deleted providers
                active_logos = {k: v for k, v in all_logos.items() if k not in st.session_state.deleted_providers}

                override_count = len(st.session_state.logo_overrides)
                deleted_count = len(st.session_state.deleted_providers)

                status_parts = [f"Total providers: {len(active_logos)}"]
                if override_count > 0:
                    status_parts.append(f"**🔧 {override_count} modified**")
                if deleted_count > 0:
                    status_parts.append(f"**🗑️ {deleted_count} deleted**")

                st.caption(" | ".join(status_parts))

                # Group by category
                categories = {
                    "Major Streaming Services": [],
                    "Premium Channels": [],
                    "Specialty Streaming": [],
                    "Discovery/Learning": [],
                    "Free Ad-Supported": [],
                    "Live TV / Cable": [],
                    "Rental/Purchase": []
                }

                # Categorize providers (simple keyword matching)
                for provider in sorted(active_logos.keys()):
                    if provider in ["netflix", "prime video", "amazon prime video", "hulu", "disney plus", "disney+",
                                   "max", "hbo max", "paramount plus", "paramount+", "peacock", "peacock premium",
                                   "apple tv plus", "apple tv+"]:
                        categories["Major Streaming Services"].append(provider)
                    elif provider in ["showtime", "starz", "mgm plus", "amc+", "bet+", "espn+"]:
                        categories["Premium Channels"].append(provider)
                    elif provider in ["crunchyroll", "shudder", "acorn tv", "sundance now", "criterion channel"]:
                        categories["Specialty Streaming"].append(provider)
                    elif provider in ["youtube premium", "discovery plus", "discovery+"]:
                        categories["Discovery/Learning"].append(provider)
                    elif provider in ["tubi", "pluto tv", "freevee", "amazon freevee", "the roku channel", "roku channel", "plex", "xumo play"]:
                        categories["Free Ad-Supported"].append(provider)
                    elif provider in ["fubotv", "fubo tv", "sling tv", "directv stream", "spectrum on demand"]:
                        categories["Live TV / Cable"].append(provider)
                    else:
                        categories["Rental/Purchase"].append(provider)

                # Display by category
                for category, providers in categories.items():
                    if providers:
                        with st.expander(f"**{category}** ({len(providers)} providers)"):
                            for provider in providers:
                                # Add border container for each row
                                with st.container(border=True):
                                    logo_url = get_provider_logo_url(provider)

                                    col1, col2, col3, col4 = st.columns([1, 5, 0.5, 0.5])
                                    with col1:
                                        if logo_url:
                                            st.image(logo_url, width=40)
                                        else:
                                            st.write(f"{ICONS['error']}")

                                    with col2:
                                        # Show if this provider has an override
                                        has_override = 'logo_overrides' in st.session_state and provider in st.session_state.logo_overrides
                                        if has_override:
                                            st.caption(f"**{provider}** 🔧 _(modified)_")
                                        else:
                                            st.caption(f"**{provider}**")

                                        if logo_url:
                                            st.caption(f"`{logo_url}`")
                                        else:
                                            st.caption("_No logo URL assigned_")

                                    with col3:
                                        if st.button("✏️", key=f"edit_{provider}", help=f"Edit {provider} logo URL"):
                                            st.session_state[f"editing_{provider}"] = True
                                            st.rerun()

                                    with col4:
                                        if st.button(ICONS["delete"], key=f"delete_{provider}", help=f"Delete {provider} from system"):
                                            # Initialize session state if needed
                                            if 'logo_overrides' not in st.session_state:
                                                st.session_state.logo_overrides = load_logo_overrides(client)
                                            if 'deleted_providers' not in st.session_state:
                                                st.session_state.deleted_providers = load_deleted_providers(client)

                                            # Add to deleted list
                                            if provider not in st.session_state.deleted_providers:
                                                st.session_state.deleted_providers.append(provider)
                                                save_deleted_providers(client, st.session_state.deleted_providers)

                                            # Also remove any override if it exists
                                            if provider in st.session_state.logo_overrides:
                                                del st.session_state.logo_overrides[provider]
                                                save_logo_overrides(client, st.session_state.logo_overrides)

                                            st.toast(f"{ICONS['check']} Deleted {provider}")
                                            st.rerun()

                                # Edit mode
                                if st.session_state.get(f"editing_{provider}", False):
                                    st.markdown(f"**Edit logo URL for: {provider}**")
                                    new_url = st.text_input(
                                        "Logo URL",
                                        value=logo_url or "",
                                        key=f"url_{provider}",
                                        placeholder="https://images.justwatch.com/icon/..."
                                    )

                                    col_save, col_cancel = st.columns(2)
                                    with col_save:
                                        if st.button("💾 Save", key=f"save_{provider}"):
                                            # Initialize logo_overrides if it doesn't exist
                                            if 'logo_overrides' not in st.session_state:
                                                st.session_state.logo_overrides = load_logo_overrides(client)

                                            # Store the new URL in session state and persist to file
                                            st.session_state.logo_overrides[provider] = new_url
                                            save_logo_overrides(client, st.session_state.logo_overrides)

                                            st.session_state[f"editing_{provider}"] = False
                                            st.success(f"{ICONS['check']} Logo URL updated for {provider} and saved to {LOGO_OVERRIDES_FILE}!")
                                            st.rerun()

                                    with col_cancel:
                                        if st.button(f"{ICONS['error']} Cancel", key=f"cancel_{provider}"):
                                            st.session_state[f"editing_{provider}"] = False
                                            st.rerun()

                                    st.write("---")

                st.write("---")

                # Scheduled Tasks Section with border
                with st.container(border=True):
                    st.markdown("**⏰ Scheduled Tasks**")
                    st.caption("Test automated email reminders and weekly previews")

                    # Show scheduled jobs
                    if scheduler:
                        jobs = scheduler.get_jobs()
                        if jobs:
                            st.info(f"{ICONS['check']} {len(jobs)} scheduled jobs running")
                            for job in jobs:
                                st.caption(f"• {job.name} - Next run: {job.next_run_time.strftime('%Y-%m-%d %I:%M %p') if job.next_run_time else 'N/A'}")
                        else:
                            st.warning("No scheduled jobs found")

                    # Test buttons
                    col_test1, col_test2 = st.columns(2)

                    with col_test1:
                        if st.button("📧 Test Daily Reminders", use_container_width=True, help="Manually trigger daily reminders now"):
                            with st.spinner("Sending daily reminders..."):
                                try:
                                    scheduler.test_daily_reminders_now()
                                    st.success(f"{ICONS['check']} Daily reminders triggered! Check your email and in-app notifications.")
                                except Exception as e:
                                    st.error(f"{ICONS['error']} Error: {e}")

                    with col_test2:
                        if st.button("📅 Test Weekly Preview", use_container_width=True, help="Manually trigger weekly preview now"):
                            with st.spinner("Sending weekly previews..."):
                                try:
                                    scheduler.test_weekly_preview_now()
                                    st.success(f"{ICONS['check']} Weekly preview triggered! Check your email and in-app notifications.")
                                except Exception as e:
                                    st.error(f"{ICONS['error']} Error: {e}")

                    st.caption("⏰ Daily reminders run automatically at 8:00 AM EST")
                    st.caption("📅 Weekly previews run automatically on Sundays at 6:00 PM EST")

                st.write("---")

                # Show Status Tracking Section with border
                with st.container(border=True):
                    st.markdown("**📊 Show Status Tracking**")
                    st.caption("Check show status from TMDB (Returning Series, Ended, Canceled)")

                    if st.button("🔍 Check All Show Statuses", use_container_width=True, help="Check TMDB for status updates on all your shows"):
                        with st.spinner("Checking show statuses from TMDB..."):
                            try:
                                user_id = get_user_id()
                                stats = show_status.check_all_shows_status(client, user_id)

                                st.success(f"{ICONS['check']} Status check complete!")
                                st.caption(f"📊 Total shows: {stats['total']}")
                                st.caption(f"🔄 Updated: {stats['updated']}")
                                st.caption(f"✓ Unchanged: {stats['unchanged']}")
                                if stats['errors'] > 0:
                                    st.caption(f"⚠️ Errors: {stats['errors']}")

                                if stats['updated'] > 0:
                                    st.info("📬 Check your notifications for any status changes!")
                            except Exception as e:
                                st.error(f"{ICONS['error']} Error: {e}")

                    st.caption("💡 Show statuses are automatically checked when you add a show to your watchlist")

                st.write("---")

                # User Management Section with border
                with st.container(border=True):
                    st.markdown("**👥 User Management**")
                    st.caption("Manage user roles and permissions")

                    # Get current admin user ID
                    admin_user_id = get_user_id()

                    # Get all users
                    all_users = auth.list_all_users(client)

                    if not all_users:
                        st.info("No users found in the system")
                    else:
                        # Count by role
                        admin_count = sum(1 for u in all_users if u.get('user_role') == 'admin')
                        user_count = sum(1 for u in all_users if u.get('user_role') == 'user')

                        st.caption(f"📊 Total users: {len(all_users)} | 👑 Admins: {admin_count} | 👤 Users: {user_count}")

                        st.write("")

                        # Display users in a table-like format
                        for user in all_users:
                            user_id = user.get('id')
                            email = user.get('email', 'Unknown')
                            role = user.get('user_role', 'user')
                            is_current_user = (user_id == admin_user_id)

                            with st.container(border=True):
                                col1, col2, col3 = st.columns([3, 1, 1])

                                with col1:
                                    # Show email and role
                                    role_emoji = ICONS["admin"] if role == "admin" else ICONS["person"]
                                    current_badge = " **(You)**" if is_current_user else ""
                                    st.markdown(f"{role_emoji} **{email}**{current_badge}")
                                    st.caption(f"Role: {role.capitalize()}")

                                with col2:
                                    # Promote button (only for regular users)
                                    if role == "user":
                                        if st.button("⬆️ Make Admin", key=f"promote_{user_id}", use_container_width=True):
                                            success, message = auth.promote_to_admin(client, user_id, admin_user_id)
                                            if success:
                                                st.success(message)
                                                st.rerun()
                                            else:
                                                st.error(message)

                                with col3:
                                    # Demote button (only for admins, not yourself)
                                    if role == "admin" and not is_current_user:
                                        if st.button("⬇️ Remove Admin", key=f"demote_{user_id}", use_container_width=True):
                                            success, message = auth.demote_to_user(client, user_id, admin_user_id)
                                            if success:
                                                st.success(message)
                                                st.rerun()
                                            else:
                                                st.error(message)
                                    elif is_current_user and role == "admin":
                                        st.caption("_(Cannot demote yourself)_")

                        st.write("")
                        st.info("💡 **Tip:** At least one admin must exist at all times. You cannot demote yourself or the last remaining admin.")

        with tab4:
            st.markdown("**🔔 Customize Your Notifications**")
            st.caption("Every alert StreamGenie can send you. Choose how you want each one — by email, "
                       "in the 🔔 sidebar, both, or off.")

            user_id = get_user_id()
            user_prefs = preferences.get_or_create_preferences(client, user_id)

            # (label, description, email_key, email_default, inapp_key, inapp_default)
            _NOTIFS = [
                (":material/tv: New episode airing",
                 "A show you track has an episode airing today.",
                 "email_new_episodes", True, "inapp_new_episodes", True),
                (":material/calendar_today: Weekly preview",
                 "A weekly digest of everything airing in the next 7 days.",
                 "email_weekly_preview", True, "inapp_weekly_preview", True),
                (":material/check_circle: Series finale (Ended)",
                 "A show you track has ended.",
                 "email_series_finale", True, "inapp_series_finale", True),
                (":material/block: Series cancelled",
                 "A show you track was cancelled.",
                 "email_series_cancelled", True, "inapp_series_cancelled", True),
                (":material/add: Show added / status change",
                 "A show is added to your watchlist or otherwise changes status.",
                 "email_show_added", False, "inapp_show_added", True),
            ]
            # Leaving-soon row appears once its DB columns exist (after the migration)
            if "inapp_leaving_soon" in user_prefs:
                _NOTIFS.append((
                    ":material/schedule: Leaving soon",
                    "A show you track is about to leave a streaming service.",
                    "email_leaving_soon", False, "inapp_leaving_soon", True))

            hdr = st.columns([5, 1.3, 1.3])
            hdr[0].markdown("**Notification**")
            hdr[1].markdown("**:material/email: Email**")
            hdr[2].markdown("**:material/notifications: In-app**")
            st.divider()

            _new_prefs = {}
            for label, desc, ek, ed, ik, idf in _NOTIFS:
                row = st.columns([5, 1.3, 1.3])
                with row[0]:
                    st.markdown(f"**{label}**")
                    st.caption(desc)
                _new_prefs[ek] = row[1].checkbox(label, value=user_prefs.get(ek, ed),
                                                 key=f"pw_{ek}", label_visibility="collapsed")
                _new_prefs[ik] = row[2].checkbox(label, value=user_prefs.get(ik, idf),
                                                 key=f"pw_{ik}", label_visibility="collapsed")
                st.divider()

            if st.button(":material/save: Save notification preferences", use_container_width=True, type="primary"):
                if preferences.update_preferences(client, user_id, _new_prefs):
                    st.success("Saved! Changes apply on the next daily/weekly run.")
                else:
                    st.error("Couldn't save — please try again.")

            st.info("💡 In-app alerts always show in the 🔔 sidebar. Email also needs a verified address "
                    "(Email Reminders tab). **Leaving-soon** alerts aren't toggle-able yet — tell me if you "
                    "want them added here.")

        st.write("---")
else:
    region = DEFAULT_REGION

# Note: Background scheduler initialized at top of file via scheduled_tasks.init_scheduler()

# ── Show-detail page (PDP) router: ?show=<id> takes over the page. Driven by the URL
#    so the browser Back button returns to the list (and the page is bookmarkable). ──
if "show" in st.query_params:
    try:
        _sid = int(st.query_params["show"])
    except Exception:
        _sid = None
    if _sid is not None:
        _show = st.session_state.get("_showcache", {}).get(_sid) or {"tmdb_id": _sid}
        render_show_page(_show, client, get_user_id())
        st.stop()
    else:
        st.query_params.clear()

# ── Main page: tabbed layout (Search / discovery / watchlist) ──
_dismissed_ids = dismissed.get_dismissed(client, get_user_id())
_wl_ids = {r.get("tmdb_id") for r in list_shows(client)}

def _add_discovered(tmdb_id, title, overview, poster_path):
    upsert_show(client, tmdb_id, title, region, True, None, overview or "", poster_path, "Multiple Providers")

_main_upcoming, _main_watch, _main_new, _main_trending, _main_top, _main_grow, _main_search = st.tabs([
    ":material/upcoming: Upcoming", ":material/tv: Your Watchlist",
    ":material/fiber_new: New This Month", ":material/trending_up: Trending",
    ":material/star: Top Rated", ":material/playlist_add: Grow Watchlist",
    ":material/search: Search",
])

with _main_upcoming:
    _up_rows = refresh_stale_air_dates(client, list_shows(client))
    render_upcoming(_up_rows, as_tab=True)

with _main_search:
    # Vertical layout: Search on top, watchlist below
    search_header = st.columns([8, 1])
    with search_header[0]:
        st.subheader(f"{ICONS['search']} Search TV Shows")
    with search_header[1]:
        if st.button(f"{ICONS['home']} Reset", help="Clear search and return to top", use_container_width=True):
            st.session_state.clear_search = True
            st.rerun()

    st.caption(f"Searching in region: **{region}** — Shows availability for all streaming services")

    # Use session state to track when to clear search
    if 'clear_search' not in st.session_state:
        st.session_state.clear_search = False

    # Clear the search if flag is set
    if st.session_state.clear_search:
        st.session_state.clear_search = False
        st.rerun()

    q = st.text_input("Search for a TV show", "", placeholder="Wednesday, Stranger Things, Squid Game...", key="search_input")
    if q:
        try:
            results = search_tv(q)
        except Exception as e:
            st.error(f"TMDB error: {e}")
            results = []

        if not results:
            st.info("No results. Try a different title.")
        else:
            # Add filters
            with st.expander(f"{ICONS['filter']} Filter Results", expanded=False):
                # Mobile-friendly: Stack filters vertically instead of side-by-side

                # Genre filter
                all_genres = set()
                for r in results:
                    genre_ids = r.get("genre_ids", [])
                    all_genres.update(genre_ids)

                # TMDB genre mapping
                genre_map = {
                    10759: "Action & Adventure", 16: "Animation", 35: "Comedy",
                    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
                    10762: "Kids", 9648: "Mystery", 10763: "News", 10764: "Reality",
                    10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk",
                    10768: "War & Politics", 37: "Western"
                }

                available_genres = sorted([genre_map.get(gid, f"Genre {gid}") for gid in all_genres])
                selected_genres = st.multiselect(
                    "Filter by Genre",
                    available_genres,
                    default=[],
                    help="Select one or more genres to filter"
                )

                # Year filter
                years = [r.get("first_air_date", "")[:4] for r in results if r.get("first_air_date")]
                years = [int(y) for y in years if y.isdigit()]

                if years and len(set(years)) > 1:  # Only show slider if there's a range
                    min_year = min(years)
                    max_year = max(years)
                    year_range = st.slider(
                        "Filter by Year",
                        min_value=min_year,
                        max_value=max_year,
                        value=(min_year, max_year),
                        help="Adjust the range to filter by premiere year"
                    )
                elif years:
                    # All shows from same year
                    year_range = (min(years), max(years))
                    st.caption(f"All results from {min(years)}")
                else:
                    year_range = None

            # Apply filters
            filtered_results = results

            if selected_genres:
                # Get genre IDs from selected genre names
                reverse_genre_map = {v: k for k, v in genre_map.items()}
                selected_genre_ids = [reverse_genre_map[g] for g in selected_genres if g in reverse_genre_map]

                filtered_results = [
                    r for r in filtered_results
                    if any(gid in r.get("genre_ids", []) for gid in selected_genre_ids)
                ]

            if year_range:
                filtered_results = [
                    r for r in filtered_results
                    if r.get("first_air_date") and r.get("first_air_date")[:4].isdigit()
                    and year_range[0] <= int(r.get("first_air_date")[:4]) <= year_range[1]
                ]

            # Show result count
            if filtered_results != results:
                st.caption(f"Showing {len(filtered_results)} of {len(results)} results")

            # Which (show, service) pairs are already on the watchlist (for "in your list")
            _wl_now = list_shows(client)
            owned_pairs = {(rr.get("tmdb_id"), normalize_provider_name(rr.get("provider_name") or ""))
                           for rr in _wl_now}

            for r in filtered_results[:20]:
                # Add padding above each result
                st.markdown("<div style='padding-top: 10px;'></div>", unsafe_allow_html=True)

                cols = st.columns([2, 5, 3])
                poster_path = r.get("poster_path")
                title = r.get("name") or r.get("original_name") or "Untitled"
                tmdb_id = r.get("id")
                overview = (r.get("overview") or "").strip()

                with cols[0]:
                    clickable_poster(tmdb_id, poster_path)

                # Provider + next-air lookup (shared by the center + right columns)
                next_air = None
                prov = None
                available_provider_names = []
                try:
                    det = tv_details(tmdb_id)
                    prov = tv_watch_providers(tmdb_id)
                    next_air = discover_next_air_date(det)
                    all_providers = get_all_providers_in_region(prov, region)
                    _uniq = {}
                    for _plist in all_providers.values():
                        for _p in _plist:
                            _uniq.setdefault(normalize_provider_name(_p), _p)
                    available_provider_names = sorted(_uniq.keys())
                except Exception:
                    pass

                # CENTER column: title + next-episode date + description
                with cols[1]:
                    clickable_title(title, {"tmdb_id": tmdb_id, "title": title, "poster_path": poster_path, "overview": overview})
                    if next_air:
                        try:
                            _d = dt.date.fromisoformat(next_air)
                            _days = (_d - dt.date.today()).days
                            _when = "today" if _days == 0 else (f"in {_days} days" if _days > 0 else f"{abs(_days)} days ago")
                            st.caption(f"📅 Next episode: {next_air} ({_when})")
                        except Exception:
                            st.caption(f"📅 Next episode: {next_air}")
                    st.write((overview[:400] + "…") if len(overview) > 400 else (overview or "_No synopsis available._"))

                # RIGHT column: streaming-service buttons (or ":blue[in your list]")
                with cols[2]:
                    if available_provider_names:
                        st.markdown("**Add on:**")
                        for provider in available_provider_names:
                            np_ = normalize_provider_name(provider)
                            if (tmdb_id, np_) in owned_pairs:
                                st.markdown(f":blue[✓ {np_} — in your list]")
                            else:
                                _onp = is_on_provider_in_region(prov, provider, region) if prov else False
                                st.button(f"➕ {np_}", key=f"add_{tmdb_id}_{provider.replace(' ', '_')}",
                                          use_container_width=True, on_click=_wl_add,
                                          args=(client, tmdb_id, title, region, _onp, next_air, overview, poster_path, np_))
                    else:
                        st.caption("📺 Not on streaming here — add to track manually:")
                        for provider in ["Netflix", "Prime Video", "Hulu", "Disney+", "Max", "Paramount+",
                                         "ESPN", "ABC", "NBC", "CBS", "Fox", "Broadcast TV"]:
                            if (tmdb_id, normalize_provider_name(provider)) in owned_pairs:
                                st.markdown(f":blue[✓ {provider} — in your list]")
                            else:
                                st.button(f"➕ {provider}", key=f"add_manual_{tmdb_id}_{provider.replace(' ', '_')}",
                                          use_container_width=True, on_click=_wl_add,
                                          args=(client, tmdb_id, title, region, False, next_air, overview, poster_path, provider))

                # Add padding below each result
                st.markdown("<div style='padding-bottom: 10px;'></div>", unsafe_allow_html=True)


with _main_new:
    st.caption("Shows that premiered in the last 30 days")
    new_shows = [s for s in get_new_shows(region, limit=12) if s.get("id") not in _dismissed_ids][:5]

    if new_shows:
        for show in new_shows:
            poster_path = show.get("poster_path")
            title = show.get("name", "Unknown")
            tmdb_id = show.get("id")
            first_air = show.get("first_air_date", "")
            overview = show.get("overview", "")
            vote_average = show.get("vote_average", 0)

            # Use same column layout as watchlist: Poster | Title+Info | Date | Actions
            cols = st.columns([2, 4, 2, 2])

            # Poster
            with cols[0]:
                clickable_poster(tmdb_id, poster_path)

            # Title and info
            with cols[1]:
                clickable_title(title, {"tmdb_id": tmdb_id, "title": title, "poster_path": poster_path, "overview": overview})
                if vote_average:
                    st.caption(f"{ICONS['star']} {vote_average:.1f}/10")
                if overview:
                    st.caption(overview[:80] + "..." if len(overview) > 80 else overview)

            # Date
            with cols[2]:
                if first_air:
                    st.markdown(f"**{first_air}**")
                    st.caption(f"{ICONS['calendar']} Premiered")

            # Actions
            with cols[3]:
                if st.button(f"{ICONS['add']}", key=f"new_show_{tmdb_id}", use_container_width=True, type="primary", help="Add to watchlist"):
                    try:
                        upsert_show(client, tmdb_id, title, region, False, first_air, overview, poster_path, "Multiple Providers")
                        st.success(f"Added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error")
                if st.button(":material/block:", key=f"dis_new_{tmdb_id}", use_container_width=True, help="Not interested — hide this"):
                    dismissed.dismiss(client, get_user_id(), tmdb_id)
                    st.rerun()
    else:
        st.info("No new shows in the last 30 days")


with _main_trending:
    st.caption("Most popular and talked-about shows this week")
    trending_shows = [s for s in get_trending_shows(limit=12) if s.get("id") not in _dismissed_ids][:5]

    if trending_shows:
        for show in trending_shows:
            poster_path = show.get("poster_path")
            title = show.get("name", "Unknown")
            tmdb_id = show.get("id")
            vote_average = show.get("vote_average", 0)
            first_air = show.get("first_air_date", "")
            overview = show.get("overview", "")

            # Use same column layout as watchlist: Poster | Title+Info | Date | Actions
            cols = st.columns([2, 4, 2, 2])

            # Poster
            with cols[0]:
                clickable_poster(tmdb_id, poster_path)

            # Title and info
            with cols[1]:
                clickable_title(title, {"tmdb_id": tmdb_id, "title": title, "poster_path": poster_path, "overview": overview})
                if vote_average:
                    st.caption(f"{ICONS['star']} {vote_average:.1f}/10")
                if overview:
                    st.caption(overview[:80] + "..." if len(overview) > 80 else overview)

            # Date/status
            with cols[2]:
                if first_air:
                    year = first_air[:4]
                    st.markdown(f"**{year}**")
                st.caption(f"{ICONS['trending']} Trending")

            # Actions
            with cols[3]:
                if st.button(f"{ICONS['add']}", key=f"trending_{tmdb_id}", use_container_width=True, type="primary", help="Add to watchlist"):
                    try:
                        upsert_show(client, tmdb_id, title, region, False, first_air, overview, poster_path, "Multiple Providers")
                        st.success(f"Added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error")
                if st.button(":material/block:", key=f"dis_trend_{tmdb_id}", use_container_width=True, help="Not interested — hide this"):
                    dismissed.dismiss(client, get_user_id(), tmdb_id)
                    st.rerun()
    else:
        st.info("No trending shows available")


with _main_top:
    st.caption("All-time highest rated shows on TMDB")
    top_rated_shows = [s for s in get_top_rated_shows(limit=12) if s.get("id") not in _dismissed_ids][:5]

    if top_rated_shows:
        for show in top_rated_shows:
            poster_path = show.get("poster_path")
            title = show.get("name", "Unknown")
            tmdb_id = show.get("id")
            vote_average = show.get("vote_average", 0)
            first_air = show.get("first_air_date", "")
            overview = show.get("overview", "")

            # Use same column layout as watchlist: Poster | Title+Info | Date | Actions
            cols = st.columns([2, 4, 2, 2])

            # Poster
            with cols[0]:
                clickable_poster(tmdb_id, poster_path)

            # Title and info
            with cols[1]:
                clickable_title(title, {"tmdb_id": tmdb_id, "title": title, "poster_path": poster_path, "overview": overview})
                if vote_average:
                    st.caption(f"{ICONS['star']} {vote_average:.1f}/10")
                if overview:
                    st.caption(overview[:80] + "..." if len(overview) > 80 else overview)

            # Date/year
            with cols[2]:
                if first_air:
                    year = first_air[:4]
                    st.markdown(f"**{year}**")
                st.caption(f"{ICONS['rated']} Top Rated")

            # Add button
            with cols[3]:
                if st.button(f"{ICONS['add']}", key=f"toprated_{tmdb_id}", use_container_width=True, type="primary", help="Add to watchlist"):
                    try:
                        upsert_show(client, tmdb_id, title, region, False, first_air, overview, poster_path, "Multiple Providers")
                        st.success(f"Added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error")
                if st.button(":material/block:", key=f"dis_top_{tmdb_id}", use_container_width=True, help="Not interested — hide this"):
                    dismissed.dismiss(client, get_user_id(), tmdb_id)
                    st.rerun()
    else:
        st.info("No top rated shows available")


with _main_grow:
    dtab1, dtab2, dtab3 = st.tabs([
        "🔎 New & Returning on Your Services", "📥 Import Netflix History",
        ":material/sports_football: Follow Your Sports Teams"])
    with dtab1:
        discover.render_discover_section(region, _wl_ids, _add_discovered)
    with dtab2:
        discover.render_netflix_import(_wl_ids, _add_discovered)
    with dtab3:
        st.caption("Follow your sports teams — games show up in **Upcoming** like episodes, with TV "
                   "networks and a link to regional coverage maps.")
        _leagues = list(sports.LEAGUES.keys())
        if st.session_state.get("sports_league") not in _leagues:
            st.session_state["sports_league"] = _leagues[0]
        # League picker — logos
        _lc = st.columns(len(_leagues))
        for _i, _lk0 in enumerate(_leagues):
            with _lc[_i]:
                _llogo = sports.league_logo(_lk0)
                if _llogo:
                    st.image(_llogo, use_column_width=True)
                _is_sel = st.session_state["sports_league"] == _lk0
                if st.button(sports.league_label(_lk0), key=f"lgsel_{_lk0}", use_container_width=True,
                             type="primary" if _is_sel else "secondary"):
                    st.session_state["sports_league"] = _lk0
                    st.rerun()
        _lk = st.session_state["sports_league"]
        _lab = sports.league_label(_lk).split()[-1]
        _teams = sports.get_teams(_lk)
        if not _teams:
            st.info("Couldn't load teams right now — try again shortly.")
        else:
            st.markdown(f"#### {sports.league_label(_lk)} — pick a team to follow")
            _q = st.text_input("Filter teams", "", key=f"team_filter_{_lk}",
                               placeholder="Type to filter…", label_visibility="collapsed")
            if _q:
                _ql = _q.lower()
                _teams = [t for t in _teams
                          if _ql in (t.get("name") or "").lower() or _ql in (t.get("abbrev") or "").lower()]
            _per = 6
            for _i in range(0, len(_teams), _per):
                _gc = st.columns(_per)
                for _j, _t in enumerate(_teams[_i:_i + _per]):
                    with _gc[_j]:
                        if _t.get("logo"):
                            st.image(_t["logo"], use_column_width=True)
                        st.caption(f"**{_t.get('abbrev') or _t['name']}**")
                        _neg = sports.encode_id(_lk, _t["id"])
                        if _neg in _wl_ids:
                            st.markdown(":blue[✓ Following]")
                        else:
                            def _follow(_team=_t, _id=_neg, _lkx=_lk, _league=_lab):
                                _g = sports.get_team_schedule(_lkx, _team["id"])
                                _ng = sports.next_game(_g)
                                upsert_show(client, _id, _team["name"], "US", True,
                                            (_ng["date"] if _ng else None),
                                            f"{_league} team", _team.get("logo"), _league)
                            st.button(":material/add: Follow", key=f"follow_{_lk}_{_t['id']}",
                                      use_container_width=True, on_click=_follow)

    # ⏳ Leaving Soon (admin-curated) — highlights titles on the user's watchlist
    try:
        leaving_soon.render_user_section(client, watchlist_tmdb_ids=_wl_ids)
    except Exception:
        pass


with _main_watch:
    # Watchlist section below search
    st.write("---")

    # Header with icon actions and view toggle
    header_cols = st.columns([7, 1, 1, 1])
    with header_cols[0]:
        st.subheader(f"{ICONS['tv']} Your Watchlist")
    with header_cols[1]:
        # Initialize view mode if not set
        if 'view_mode' not in st.session_state:
            st.session_state.view_mode = 'grid'
    with header_cols[2]:
        if st.button(":material/grid_view:", key="grid_view", help="Grid view", use_container_width=True):
            st.session_state.view_mode = 'grid'
            st.rerun()
    with header_cols[3]:
        if st.button(":material/view_list:", key="list_view", help="List view", use_container_width=True):
            st.session_state.view_mode = 'list'
            st.rerun()

    # Export button
    if st.button(f"{ICONS['download']} Export CSV", key="export_csv_btn", use_container_width=False):
        st.session_state.show_export = True

    export_csv = st.session_state.get('show_export', False)

    rows = list_shows(client)

    # Auto-update production status for shows that don't have it
    if rows:
        user_id = get_user_id()
        for row in rows:
            # Skip sports-team rows (negative ids aren't TMDB shows)
            if (row.get('tmdb_id') or 0) < 0:
                continue
            # Check if production_status is missing or null
            if not row.get('production_status'):
                try:
                    # Silently update status in background
                    show_status.update_show_status(client, user_id, row['tmdb_id'], row['title'])
                except Exception:
                    pass  # Silently fail, don't interrupt display
        # Refresh rows after updates
        rows = list_shows(client)

    # Auto-refresh stale air dates (past dates get updated with next upcoming episode)
    if rows:
        rows = refresh_stale_air_dates(client, rows)

    if not rows:
        st.info("Your watchlist is empty. Search and add shows from above.")
    else:

        if export_csv:
            import csv, io
            df = []
            for r in rows:
                provider_name = r.get("provider_name", DEFAULT_PROVIDER)
                df.append({
                    "Title": r["title"],
                    "Region": r["region"],
                    "Provider": provider_name,
                    "Available?": "Yes" if r["on_provider"] else "No",
                    "Next Air Date": r["next_air_date"] or "",
                    "Status": format_status(bool(r["on_provider"]), r["next_air_date"], provider_name),
                })
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=list(df[0].keys()))
            writer.writeheader()
            writer.writerows(df)
            st.download_button("📥 Download watchlist.csv", buf.getvalue(), file_name="watchlist.csv", mime="text/csv", use_container_width=True)

        st.write("---")

        # (Upcoming episodes now live in their own top-level "📅 Upcoming" tab)

        # Get current view mode
        view_mode = st.session_state.get('view_mode', 'grid')

        # Sort control — single dropdown, works in both grid and list views
        SORT_OPTS = {
            "Next episode (soonest)": ("date", "asc"),
            "Next episode (latest)": ("date", "desc"),
            "Recently added": ("added", "desc"),
            "Oldest added": ("added", "asc"),
            "Title (A\u2013Z)": ("title", "asc"),
            "Title (Z\u2013A)": ("title", "desc"),
            "Provider": ("service", "asc"),
        }
        _opt_keys = list(SORT_OPTS.keys())
        sc = st.columns([2, 3])
        with sc[0]:
            sort_label = st.selectbox("Sort by", _opt_keys, key="sort_label")
        sort_by, sort_order = SORT_OPTS[sort_label]

        if sort_by == "title":
            rows = sorted(rows, key=lambda x: x["title"].lower(), reverse=(sort_order == "desc"))
        elif sort_by == "date":
            def _date_key(r):
                d = r.get("next_air_date")
                if not d:
                    return "9999-99-99" if sort_order == "asc" else "0000-00-00"
                return d
            rows = sorted(rows, key=_date_key, reverse=(sort_order == "desc"))
        elif sort_by == "service":
            rows = sorted(rows, key=lambda x: normalize_provider_name(x.get("provider_name", "")).lower(), reverse=(sort_order == "desc"))
        elif sort_by == "added":
            rows = sorted(rows, key=lambda x: x.get("created_at") or "", reverse=(sort_order == "desc"))

        st.caption(f"Tracking {len(rows)} show(s) \u2022 {sort_label}")

        # Watched-episode counts for badges (one query; {} if table not yet created)
        _wcounts = watched.watched_counts(client, get_user_id())

        def _status_group(rr):
            ss = (rr.get("show_status") or "")
            ps = (rr.get("production_status") or "")
            if ss == "Canceled" or ps == "CANCELED":
                return "canceled"
            if ss == "Ended" or ps == "ENDED":
                return "ended"
            return "active"

        _groups = {"active": [], "canceled": [], "ended": []}
        for r in rows:
            _groups[_status_group(r)].append(r)

        def _render_group(group, empty_msg):
            if not group:
                st.info(empty_msg)
                return
            if view_mode == 'grid':
                render_grid_gallery(group, client, _wcounts)   # poster-tile gallery
            else:
                for r in group:
                    render_show_row(r, 'list', client, _wcounts)  # detailed rows w/ episode guide

        _t_active, _t_canceled, _t_ended = st.tabs([
            f"📺 Active ({len(_groups['active'])})",
            f"🚫 Canceled ({len(_groups['canceled'])})",
            f"✅ Ended ({len(_groups['ended'])})",
        ])
        with _t_active:
            _render_group(_groups['active'], "No active shows.")
        with _t_canceled:
            _render_group(_groups['canceled'], "No canceled shows. 🎉")
        with _t_ended:
            _render_group(_groups['ended'], "No ended shows yet.")