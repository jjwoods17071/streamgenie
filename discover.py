"""
Grow-the-watchlist tools:
  1. "New & Returning on Your Services" — TMDB Discover filtered to the user's
     streaming providers, surfacing returning series (the new-episode goldmine).
  2. Netflix viewing-history import — parse ViewingActivity.csv, match to TMDB,
     bulk-add still-returning series.

Self-contained TMDB access (TMDB_API_KEY from env). The actual watchlist write is
done via an injected add_fn so this module stays decoupled from app.py.
"""
import os
import re
import io
import csv
import datetime as dt
from typing import List, Dict, Any, Callable, Set, Optional

import requests
import streamlit as st

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"

# TMDB watch-provider IDs (US). Lists allow legacy/duplicate IDs for one brand.
PROVIDERS: Dict[str, List[int]] = {
    "Netflix": [8],
    "Max": [1899, 384],                 # Max / HBO Max
    "Apple TV+": [350, 2552],
    "Paramount+": [531, 1853],          # Paramount+ / with Showtime
    "Amazon Prime Video": [9, 119],
    "Hulu": [15],
    "Disney+": [337],
    "Peacock": [386, 387],
    "Starz": [43],
    "Showtime": [37],
    "AMC+": [526],
}

# TMDB tv status codes for /discover/tv with_status
STATUS_RETURNING = 0


def _get(path: str, **params) -> Dict[str, Any]:
    params.update(api_key=TMDB_API_KEY, language="en-US")
    r = requests.get(f"{TMDB_BASE}{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def poster(p: Optional[str], size="w185") -> Optional[str]:
    return f"{IMG}/{size}{p}" if p else None


# ---------------- provider discovery ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def discover_returning(provider_ids: tuple, region: str = "US", pages: int = 2) -> List[Dict[str, Any]]:
    """Popular *returning* series available on the given providers (deduped)."""
    if not provider_ids:
        return []
    seen, out = set(), []
    for page in range(1, pages + 1):
        try:
            data = _get("/discover/tv",
                        with_watch_providers="|".join(str(i) for i in provider_ids),
                        watch_region=region,
                        with_status=STATUS_RETURNING,
                        sort_by="popularity.desc",
                        page=page)
        except Exception:
            break
        for s in data.get("results", []):
            if s["id"] in seen:
                continue
            seen.add(s["id"])
            fa = s.get("first_air_date") or ""
            out.append({
                "tmdb_id": s["id"], "title": s.get("name", "Unknown"),
                "year": fa[:4] if fa else "—",
                "poster_path": s.get("poster_path"),
                "overview": s.get("overview", ""),
                "vote": s.get("vote_average", 0),
            })
    return out


def render_discover_section(region: str, watchlist_ids: Set[int], add_fn: Callable) -> None:
    st.caption("Pick your services and we'll surface **returning** shows on them — the ones with new episodes coming.")
    default = [p for p in ["Max", "Netflix", "Apple TV+", "Paramount+", "Amazon Prime Video", "Hulu"]
               if p in PROVIDERS]
    picks = st.multiselect("Your streaming services", list(PROVIDERS.keys()),
                           default=st.session_state.get("disc_providers", default),
                           key="disc_providers")
    if not st.button("🔎 Find new & returning shows", key="disc_go"):
        return

    ids = tuple(i for p in picks for i in PROVIDERS[p])
    shows = [s for s in discover_returning(ids, region) if s["tmdb_id"] not in watchlist_ids]
    if not shows:
        st.info("Nothing new found (everything popular is already on your watchlist, or no services selected).")
        return

    st.success(f"{len(shows)} returning shows on your services not yet tracked.")
    if st.button(f"➕ Add all {len(shows)}", key="disc_add_all"):
        n = 0
        for s in shows:
            try:
                add_fn(s["tmdb_id"], s["title"], s["overview"], s["poster_path"])
                n += 1
            except Exception:
                pass
        st.success(f"Added {n} shows!")
        st.rerun()

    for s in shows[:24]:
        with st.container(border=True):
            c = st.columns([1, 5, 1])
            with c[0]:
                pu = poster(s["poster_path"])
                if pu:
                    st.image(pu, use_container_width=True)
            with c[1]:
                st.markdown(f"**{s['title']}** ({s['year']})  ⭐ {s['vote']:.1f}")
                if s["overview"]:
                    st.caption(s["overview"][:160])
            with c[2]:
                if st.button("➕", key=f"disc_add_{s['tmdb_id']}", help="Add to watchlist"):
                    add_fn(s["tmdb_id"], s["title"], s["overview"], s["poster_path"])
                    st.rerun()


# ---------------- Netflix history import ----------------
_SERIES_MARKER = re.compile(r":\s*(Season|Limited Series|Part|Chapter|Volume|Series|Book|Episode|Collection)\b", re.I)


def parse_netflix_titles(raw: bytes) -> List[str]:
    """Extract unique series/movie base titles from a Netflix ViewingActivity.csv."""
    text = raw.decode("utf-8", errors="ignore")
    titles = set()
    for row in csv.DictReader(io.StringIO(text)):
        t = (row.get("Title") or row.get("title") or "").strip()
        if not t:
            continue
        base = _SERIES_MARKER.split(t)[0].strip().rstrip(":").strip()
        if base:
            titles.add(base)
    return sorted(titles)


@st.cache_data(ttl=86400, show_spinner=False)
def match_title(title: str) -> Optional[Dict[str, Any]]:
    """Best TMDB TV match for a title, with current status."""
    try:
        res = _get("/search/tv", query=title).get("results", [])
        if not res:
            return None
        top = res[0]
        det = _get(f"/tv/{top['id']}")
        return {
            "tmdb_id": top["id"], "title": top.get("name", title),
            "status": det.get("status", "Unknown"),
            "poster_path": top.get("poster_path"),
            "overview": top.get("overview", ""),
        }
    except Exception:
        return None


def render_netflix_import(watchlist_ids: Set[int], add_fn: Callable) -> None:
    st.caption("Export your history from **Netflix → Account → Viewing activity → Download all**, "
               "then upload `ViewingActivity.csv` here. We'll add the still-returning series.")
    up = st.file_uploader("Netflix ViewingActivity.csv", type=["csv"], key="nflx_csv")
    if not up:
        return
    titles = parse_netflix_titles(up.getvalue())
    st.write(f"Found **{len(titles)}** unique titles in your history. Matching to TMDB…")

    returning, other = [], 0
    prog = st.progress(0.0)
    for i, t in enumerate(titles[:200]):  # cap to keep it responsive
        m = match_title(t)
        prog.progress((i + 1) / min(len(titles), 200))
        if not m:
            continue
        if m["tmdb_id"] in watchlist_ids:
            continue
        if m["status"] in ("Returning Series", "In Production", "Planned"):
            returning.append(m)
        else:
            other += 1
    prog.empty()

    if not returning:
        st.info(f"No new still-returning series found ({other} matched titles are ended/already tracked).")
        return

    st.success(f"{len(returning)} still-returning series not yet on your watchlist "
               f"({other} others were ended or already tracked).")
    if st.button(f"➕ Add all {len(returning)} returning series", key="nflx_add_all", type="primary"):
        n = 0
        for m in returning:
            try:
                add_fn(m["tmdb_id"], m["title"], m["overview"], m["poster_path"])
                n += 1
            except Exception:
                pass
        st.success(f"Added {n} shows to your watchlist!")
        st.rerun()

    for m in returning[:30]:
        st.markdown(f"• **{m['title']}** — _{m['status']}_")
