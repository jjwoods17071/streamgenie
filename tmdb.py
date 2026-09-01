"""
One TMDB client for every module.

There were three near-identical copies of "GET a TMDB path" (movies, recs, newsletter),
which is how two of them ended up without the retry the third had. This is the single
implementation: retry on transient failures, and a small thread pool for the fan-out
fetches that dominate wall-clock.

Runtime-agnostic (no streamlit) so cron, the newsletter and the self-test can all use it.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests

import milestones

BASE = "https://api.themoviedb.org/3"

# TMDB tolerates ~50 req/s; 8 keeps us far below that while still collapsing a 40-call
# serial loop into ~5 round-trips of wall time.
MAX_WORKERS = 8


def get(path: str, **params) -> Dict[str, Any]:
    """GET a TMDB path, retrying transient failures.

    TMDB rate-limits bursts and most callers swallow exceptions into empty lists, so
    without the retry a blip reaches the user as "nothing found" rather than an error.
    Only 429/5xx and timeouts are retried — a 404 is a real answer.
    """
    key = os.getenv("TMDB_API_KEY", "").strip()
    # A v4 token goes in the Authorization header; a v3 key goes in the query string.
    headers = {"Authorization": f"Bearer {key}"} if len(key) > 40 else {}
    params.setdefault("language", "en-US")
    if not headers:
        params["api_key"] = key
    last: Optional[Exception] = None
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}{path}", params=params, headers=headers, timeout=20)
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("Retry-After") or (0.5 * (attempt + 1)))
                last = requests.HTTPError(f"HTTP {r.status_code} for {path}")
                time.sleep(min(wait, 5))
                continue
            r.raise_for_status()
            return r.json()
        except requests.Timeout as e:
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise last if last else RuntimeError(f"TMDB request failed: {path}")


def parallel_map(fn: Callable, items: Iterable, workers: int = MAX_WORKERS) -> List[Any]:
    """Map `fn` over `items` concurrently, PRESERVING ORDER, with failures as None.

    These fetches are pure independent reads, and the callers were spending ~0.5s of
    network latency each in sequence — 55 of them in one newsletter build. Order is
    preserved so downstream sorting and ranking stay deterministic.
    """
    items = list(items)
    if not items:
        return []
    if len(items) == 1:
        try:
            return [fn(items[0])]
        except Exception:
            return [None]

    def safe(x):
        try:
            return fn(x)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(safe, items))


# ---------------- show records ----------------

def shape_show(d: Dict[str, Any]) -> Dict[str, Any]:
    """The subset of a TMDB show record the app actually uses (~1.7KB vs ~3.1KB raw)."""
    return {
        "name": d.get("name"),
        "poster_path": d.get("poster_path"),
        "backdrop_path": d.get("backdrop_path"),
        "overview": d.get("overview"),
        "status": d.get("status"),
        "number_of_seasons": d.get("number_of_seasons"),
        "number_of_episodes": d.get("number_of_episodes"),
        "first_air_date": d.get("first_air_date"),
        "in_production": d.get("in_production"),
        "type": d.get("type"),
        "next_episode_to_air": d.get("next_episode_to_air"),
        "last_episode_to_air": d.get("last_episode_to_air"),
        "seasons": milestones.real_seasons(d),
    }


def fetch_shows(tv_ids) -> Dict[int, Dict[str, Any]]:
    """THE source of shaped show records. Every caller goes through here.

    Today this is TMDB. The intended next step is a shared `show_cache` table read first
    with TMDB as the miss path — see SCALING.md. It lives HERE rather than in app.py so a
    native client can use it: business logic outside the Streamlit layer is the whole
    reason the modules are import-safe.

    Fetches concurrently and skips ids that fail, so one bad id never loses the batch.
    """
    ids = list(tv_ids)
    if not ids:
        return {}
    records = parallel_map(lambda t: get(f"/tv/{t}"), ids)
    return {tid: shape_show(d) for tid, d in zip(ids, records) if d}
