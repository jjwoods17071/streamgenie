"""
Shared like-for-like recommendation engine.

Both the in-app "For You" feed and the weekly newsletter run this module. Before it
existed, the only taste-aware recommendation logic in StreamGenie lived inline in
newsletter.py — so it reached a user once a week by email and never on the page,
while the app's "For You" was a popularity sort of returning shows on your providers
(discover.discover_returning) that ignored watch history entirely.

Pipeline:
  1. seeds   — your watchlist ranked by engagement (episodes watched, pinned)
  2. pool    — TMDB /recommendations + /similar per seed, merged WITH attribution so
               every candidate remembers which of your shows produced it
  3. filter  — drop anything already tracked, dismissed, already voted on, in a
               hidden genre, or too thinly rated to trust
  4. rank    — Genie picks best fits against your 👍/👎 history; without Genie it
               falls back to a deterministic score (no hard dependency on the API)

Runtime-agnostic on purpose: no streamlit import, so cron_runner/newsletter can call
it headlessly. Caching belongs to the caller (the app wraps it in st.cache_data).
"""
import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

import requests

TMDB_BASE = "https://api.themoviedb.org/3"

# A candidate needs at least this many TMDB votes before we trust its rating —
# without a floor, obscure 10-vote shows with a 9.5 average dominate the ranking.
MIN_VOTES = 50

# TMDB's /recommendations is curated from user behaviour; /similar is a weaker
# genre/keyword match. Both are useful, recommendations more so.
_SOURCE_BONUS = {"rec": 1.0, "similar": 0.0}


def _noop(*_a, **_k) -> None:
    pass


def _tmdb(path: str, **params) -> Dict[str, Any]:
    params.update(api_key=os.getenv("TMDB_API_KEY", "").strip(), language="en-US")
    r = requests.get(f"{TMDB_BASE}{path}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_watched_counts(client, user_id: str) -> Dict[int, int]:
    """tmdb_id -> episodes watched, paging past Supabase's 1000-row response cap.

    Mirrors watched.watched_counts, which is streamlit-cached and therefore app-only;
    this plain copy keeps the headless cron/newsletter path on the same signal.
    """
    counts: Dict[int, int] = {}
    try:
        start, page = 0, 1000
        while True:
            batch = (client.table("watched_episodes").select("tmdb_id")
                     .eq("user_id", user_id)
                     .range(start, start + page - 1).execute().data or [])
            for x in batch:
                counts[x["tmdb_id"]] = counts.get(x["tmdb_id"], 0) + 1
            if len(batch) < page:
                break
            start += page
    except Exception:
        return {}
    return counts


# ---------------- 1. seeds ----------------

def seed_shows(watchlist_rows: Sequence[Dict[str, Any]],
               watched_counts: Optional[Dict[int, int]] = None,
               max_seeds: int = 6) -> List[Dict[str, Any]]:
    """The watchlist shows worth recommending FROM, best signal first.

    Engagement beats recency: a show you've watched 40 episodes of says far more
    about your taste than one you added yesterday and never opened. Pinned shows are
    an explicit "this matters to me" signal, so they rank alongside heavy viewing.
    Sports follows (negative tmdb_id) are excluded — TMDB knows nothing about them.
    """
    counts = watched_counts or {}
    tv = [r for r in watchlist_rows if (r.get("tmdb_id") or 0) > 0]

    def _rank(r):
        tid = r["tmdb_id"]
        return (-(counts.get(tid, 0)),          # most-watched first
                0 if r.get("pinned") else 1,     # pinned ahead of unpinned
                (r.get("title") or "").lower())  # stable tiebreak
    return sorted(tv, key=_rank)[:max_seeds]


# ---------------- 2. pool ----------------

def _normalize(c: Dict[str, Any], seed: Dict[str, Any], source: str) -> Dict[str, Any]:
    fa = c.get("first_air_date") or ""
    return {
        "tmdb_id": c.get("id"),
        "title": c.get("name") or "Unknown",
        "year": fa[:4] if fa else "—",
        "poster_path": c.get("poster_path"),
        "overview": c.get("overview") or "",
        "vote": c.get("vote_average") or 0,
        "votes": c.get("vote_count") or 0,
        "genre_ids": c.get("genre_ids") or [],
        "original_language": c.get("original_language"),
        "seeds": [seed.get("title")],
        "seed_ids": [seed.get("tmdb_id")],
        "sources": {source},
    }


def build_pool(seeds: Sequence[Dict[str, Any]], per_seed: int = 10,
               log: Callable = _noop) -> List[Dict[str, Any]]:
    """Merge /recommendations + /similar across every seed, keeping attribution.

    When two different shows you watch both point at the same candidate, that overlap
    is the single most useful cheap signal we have — so candidates accumulate their
    seed list rather than the first one winning.
    """
    pool: Dict[int, Dict[str, Any]] = {}
    for seed in seeds:
        sid = seed.get("tmdb_id")
        for source, path in (("rec", "recommendations"), ("similar", "similar")):
            try:
                results = _tmdb(f"/tv/{sid}/{path}").get("results", [])[:per_seed]
            except Exception as e:
                log(f"recs: {path} failed for {seed.get('title')}: {e}")
                continue
            for c in results:
                cid = c.get("id")
                if not cid:
                    continue
                if cid in pool:
                    existing = pool[cid]
                    if seed.get("title") not in existing["seeds"]:
                        existing["seeds"].append(seed.get("title"))
                        existing["seed_ids"].append(sid)
                    existing["sources"].add(source)
                else:
                    pool[cid] = _normalize(c, seed, source)
    return list(pool.values())


# ---------------- 3. filter ----------------

def taste_signals(client, user_id: str) -> Dict[str, List[str]]:
    """The user's 👍/👎 history from rec_feedback (absent table → no signal)."""
    liked, disliked = [], []
    try:
        for f in (client.table("rec_feedback").select("title,verdict")
                  .eq("user_id", user_id).execute().data or []):
            (liked if f.get("verdict") == "up" else disliked).append(f.get("title"))
    except Exception:
        pass
    return {"liked": [t for t in liked if t], "disliked": [t for t in disliked if t]}


def score(c: Dict[str, Any]) -> float:
    """Deterministic fit score — also the ordering when Genie is unavailable.

    Seed overlap dominates rating: a 7.4 show that three of your shows point at is a
    better bet than an 8.6 nobody on your list resembles.
    """
    overlap = len(c.get("seeds") or [])
    src = max((_SOURCE_BONUS.get(s, 0.0) for s in c.get("sources") or ()), default=0.0)
    return (overlap * 3.0) + float(c.get("vote") or 0) + src


def filter_pool(pool: Sequence[Dict[str, Any]], *,
                exclude_ids: Iterable[int] = (),
                exclude_titles: Iterable[str] = (),
                genre_keys_fn: Optional[Callable] = None,
                excluded_genres: Iterable[str] = (),
                min_votes: int = MIN_VOTES,
                pool_cap: int = 40) -> List[Dict[str, Any]]:
    """Drop what the user can't or shouldn't be shown, then keep the best `pool_cap`.

    genre_keys_fn is injected (genre_prefs.show_genre_keys from the app) rather than
    imported so this module stays free of streamlit for the headless cron path.
    """
    ids = {int(i) for i in exclude_ids if i is not None}
    titles = {(t or "").strip().lower() for t in exclude_titles if t}
    hidden = set(excluded_genres or ())

    out = []
    for c in pool:
        if c.get("tmdb_id") is None or int(c["tmdb_id"]) in ids:
            continue
        if (c.get("title") or "").strip().lower() in titles:
            continue
        if (c.get("votes") or 0) < min_votes:
            continue
        if hidden and genre_keys_fn and (genre_keys_fn(c) & hidden):
            continue
        out.append(c)
    return sorted(out, key=lambda c: -score(c))[:pool_cap]


# ---------------- 4. rank ----------------

def attribution(c: Dict[str, Any]) -> str:
    """'Because you watched X' — the trust lever. The seed is already known, so
    explaining a recommendation costs nothing."""
    names = [s for s in (c.get("seeds") or []) if s]
    if not names:
        return ""
    if len(names) == 1:
        return f"Because you watch {names[0]}"
    if len(names) == 2:
        return f"Because you watch {names[0]} and {names[1]}"
    return f"Because you watch {names[0]}, {names[1]} and {len(names) - 2} more"


def rank_pool(pool: Sequence[Dict[str, Any]], taste: Dict[str, List[str]],
              limit: int = 6, use_genie: bool = True,
              log: Callable = _noop) -> Dict[str, Any]:
    """Order the pool and attach a reason to each pick.

    Genie ranks for taste fit and writes a one-line spoiler-free blurb; if it's
    unavailable (no key, API error, empty response) we still return the deterministic
    top `limit` with attribution as the reason. Recommendations never hard-fail.
    """
    ranked = sorted(pool, key=lambda c: -score(c))
    ranked_by = "score"
    picks = ranked[:limit]

    if use_genie and ranked:
        try:
            import genie
            chosen = genie.rank_recommendations(ranked[:20], taste, limit=limit, log=log)
        except Exception as e:
            log(f"recs: genie ranking failed: {e}")
            chosen = None
        if chosen:
            by_title = {(c.get("title") or "").strip().lower(): c for c in ranked}
            picked = []
            for item in chosen:
                c = by_title.get((item.get("title") or "").strip().lower())
                if c and c not in picked:
                    picked.append({**c, "blurb": item.get("blurb") or ""})
            if picked:
                picks, ranked_by = picked[:limit], "genie"

    for c in picks:
        c["seed"] = (c.get("seeds") or [None])[0]      # newsletter/_week_payload contract
        c["why"] = attribution(c)
        c["reason"] = c.get("blurb") or c["why"]
    return {"picks": picks, "ranked_by": ranked_by}


# ---------------- orchestrator ----------------

def for_user(client, user_id: str, *, limit: int = 6,
             watchlist_rows: Optional[Sequence[Dict[str, Any]]] = None,
             watched_counts: Optional[Dict[int, int]] = None,
             dismissed_ids: Optional[Iterable[int]] = None,
             genre_keys_fn: Optional[Callable] = None,
             excluded_genres: Iterable[str] = (),
             max_seeds: int = 6, pool_cap: int = 40,
             use_genie: bool = True, log: Callable = _noop) -> Dict[str, Any]:
    """End-to-end recommendations for one user.

    Every input the caller already has in hand (watchlist rows, watched counts,
    dismissals) can be passed in to avoid re-querying; anything omitted is fetched.
    Returns {"picks", "pool_size", "seed_titles", "ranked_by"} and never raises —
    an empty picks list is the failure mode.
    """
    try:
        if watchlist_rows is None:
            import movies
            watchlist_rows = movies.fetch_tv_rows(
                client, user_id, "tmdb_id,title,provider_name,next_air_date")
        if dismissed_ids is None:
            try:
                dismissed_ids = {x["tmdb_id"] for x in
                                 (client.table("dismissed_shows").select("tmdb_id")
                                  .eq("user_id", user_id).execute().data or [])}
            except Exception:
                dismissed_ids = set()

        if watched_counts is None:
            watched_counts = fetch_watched_counts(client, user_id)

        seeds = seed_shows(watchlist_rows, watched_counts, max_seeds=max_seeds)
        if not seeds:
            return {"picks": [], "pool_size": 0, "seed_titles": [], "ranked_by": "none"}

        pool = build_pool(seeds, log=log)
        taste = taste_signals(client, user_id)
        filtered = filter_pool(
            pool,
            exclude_ids=set(r.get("tmdb_id") for r in watchlist_rows) | set(dismissed_ids or ()),
            exclude_titles=taste["liked"] + taste["disliked"],
            genre_keys_fn=genre_keys_fn, excluded_genres=excluded_genres,
            pool_cap=pool_cap,
        )
        result = rank_pool(filtered, taste, limit=limit, use_genie=use_genie, log=log)
        result.update(pool_size=len(filtered),
                      seed_titles=[s.get("title") for s in seeds])
        return result
    except Exception as e:
        log(f"recs: for_user failed: {e}")
        return {"picks": [], "pool_size": 0, "seed_titles": [], "ranked_by": "error"}
