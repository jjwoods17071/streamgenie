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
import difflib
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
    # Run the search on click; persist results so the list stays put after each add.
    if st.button("🔎 Find new & returning shows", key="disc_go"):
        ids = tuple(i for p in picks for i in PROVIDERS[p])
        st.session_state["disc_results"] = discover_returning(ids, region)

    found = st.session_state.get("disc_results")
    if not found:
        return

    owned = {int(x) for x in watchlist_ids if x is not None}
    not_owned = [s for s in found if int(s["tmdb_id"]) not in owned]
    already = len(found) - len(not_owned)
    note = f"**{len(not_owned)}** returning shows on your services not yet tracked"
    if already:
        note += f"  ·  **{already}** already on your watchlist (shown in blue)"
    st.success(note + ".")

    for s in found[:30]:
        with st.container(border=True):
            c = st.columns([1, 5, 2])
            with c[0]:
                pu = poster(s["poster_path"])
                if pu:
                    st.image(pu, use_column_width=True)
            with c[1]:
                st.markdown(f"**{s['title']}** ({s['year']})  ⭐ {s['vote']:.1f}")
                if s["overview"]:
                    st.caption(s["overview"][:160])
            with c[2]:
                if int(s["tmdb_id"]) in owned:
                    st.markdown(":blue[✓ In your list]")
                else:
                    # on_click keeps the results in place; the show flips to blue after adding
                    st.button("➕ Add", key=f"disc_add_{s['tmdb_id']}", use_container_width=True,
                              on_click=add_fn,
                              args=(s["tmdb_id"], s["title"], s["overview"], s["poster_path"]))


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
    """Best TMDB TV match for a title, with current status.
    Filters out movie→TV false positives (e.g. the film 'Damsel' matching an
    obscure TV series of the same name) and near-zero-signal fluke matches."""
    try:
        res = _get("/search/tv", query=title).get("results", [])
        if not res:
            return None
        top = res[0]
        norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
        toks = lambda s: set(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())
        q = norm(title)
        qt = toks(title)
        tn = norm(top.get("name", ""))
        tnt = toks(top.get("name", ""))
        ratio = difflib.SequenceMatcher(None, q, tn).ratio()

        # Movie-vs-TV disambiguation: if the most popular result across movies+TV is a
        # MOVIE whose name matches the watched title (exact OR strong fuzzy OR containment)
        # and it's at least as popular as the TV hit, the user watched the FILM — skip.
        try:
            multi = [m for m in _get("/search/multi", query=title).get("results", [])
                     if m.get("media_type") in ("movie", "tv")]
            if multi:
                best = max(multi, key=lambda m: m.get("popularity", 0) or 0)
                bn = norm(best.get("title") or best.get("name") or "")
                movie_is_q = (bn == q
                              or difflib.SequenceMatcher(None, q, bn).ratio() >= 0.80
                              or (len(q) >= 4 and (q in bn or bn in q)))
                if (best.get("media_type") == "movie" and movie_is_q and tn != q
                        and (best.get("popularity", 0) or 0) >= (top.get("popularity", 0) or 0)):
                    return None
        except Exception:
            pass

        # Title-correspondence gate: the TV hit must actually correspond to the watched
        # title — exact match, strong fuzzy, or the TV name is a subset of the query
        # (Netflix added qualifiers). This rejects loose fuzzy hits where the TV show
        # only shares a word, e.g. "Game Night"→"Hollywood Game Night",
        # "Maestro"→"Maestro in Blue", "Ice Road"→"Ice Road Truckers".
        exact = (tn == q)
        strong_fuzzy = ratio >= 0.82
        tv_subset_of_query = bool(tnt) and tnt.issubset(qt)
        if not (exact or strong_fuzzy or tv_subset_of_query):
            return None

        # Quality gate: drop obscure near-zero-signal series unless the name matches exactly
        if ((top.get("vote_count") or 0) < 3 and (top.get("popularity") or 0) < 3
                and tn != q):
            return None

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
    st.caption("Export from **netflix.com/viewingactivity → Download all** (per-profile, on the website), "
               "then upload `NetflixViewingHistory.csv` here. We'll add the still-returning series.")
    up = st.file_uploader("Netflix viewing history (.csv)", type=["csv"], key="nflx_csv")
    if not up:
        return
    titles = parse_netflix_titles(up.getvalue())
    st.write(f"Found **{len(titles)}** unique titles in your history. Matching to TMDB…")

    owned = {int(x) for x in watchlist_ids if x is not None}
    returning, ended, already, seen = [], 0, 0, set()
    prog = st.progress(0.0)
    for i, t in enumerate(titles[:200]):  # cap to keep it responsive
        m = match_title(t)
        prog.progress((i + 1) / min(len(titles), 200))
        if not m:
            continue
        tid = int(m["tmdb_id"])
        if tid in owned:                 # already on the watchlist → filter out
            already += 1
            continue
        if tid in seen:                  # duplicate match within this import
            continue
        seen.add(tid)
        if m["status"] in ("Returning Series", "In Production", "Planned"):
            returning.append(m)
        else:
            ended += 1
    prog.empty()

    if not returning:
        st.info(f"No new still-returning series found — filtered out {already} already on your watchlist and {ended} ended.")
        return

    st.success(f"{len(returning)} still-returning series not yet on your watchlist "
               f"(filtered out {already} already tracked + {ended} ended).")
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
