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
    params.update(api_key=os.getenv("TMDB_API_KEY", "").strip(), language="en-US")
    last: Optional[Exception] = None
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}{path}", params=params, timeout=15)
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
