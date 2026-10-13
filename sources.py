"""
Health probes for the external data this app depends on.

WHY THIS EXISTS: external sources change silently, and we only find out when a feature
quietly starts returning nothing. Two found on 2026-10-13 while investigating whether we
could source availability per service:

  * Apple's iTunes Search API still indexes film and TV, but `media=tvShow` and
    `media=movie` now return ZERO results. The rows are reachable only unfiltered, where
    relevance is broken — searching "Inception" returns "Ring of Fire (IMAX)". A filter
    that returns an empty list rather than an error is exactly the kind of break nothing
    notices.
  * Netflix's public Top 10 feed moved host and now answers 301 at its documented URL.

Neither is load-bearing today. Both would have been invisible. This module exists so a
source that changes shape shows up as a failing check instead of an empty page.

Every probe is read-only, hits a public endpoint, and returns a verdict rather than
raising. Runtime-agnostic (no streamlit).
"""
import logging
from typing import Any, Dict, List

import requests

log = logging.getLogger(__name__)

TIMEOUT = 20
UA = {"User-Agent": "StreamGenie source health check"}


def _probe(name: str, why: str, fn) -> Dict[str, Any]:
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {e}"
    return {"source": name, "ok": bool(ok), "detail": detail, "matters_for": why}


# ---------------------------------------------------------------- probes

def tmdb_search(api_key: str) -> Dict[str, Any]:
    """The source everything actually depends on."""
    def go():
        r = requests.get("https://api.themoviedb.org/3/search/tv",
                         params={"api_key": api_key, "query": "breaking bad"},
                         headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        hits = (r.json() or {}).get("results") or []
        if not hits:
            return False, "200 but zero results for a search that must match"
        return True, f"{len(hits)} results, top = {hits[0].get('name')!r}"
    return _probe("TMDB /search/tv", "everything", go)


def tmdb_providers(api_key: str) -> Dict[str, Any]:
    """Availability — the one thing no free alternative supplies."""
    def go():
        r = requests.get("https://api.themoviedb.org/3/tv/1396/watch/providers",
                         params={"api_key": api_key}, headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        us = ((r.json() or {}).get("results") or {}).get("US") or {}
        if not us:
            return False, "200 but no US providers for a show that has them"
        n = len(us.get("flatrate") or []) + len(us.get("buy") or [])
        return True, f"{n} US provider listings"
    return _probe("TMDB /watch/providers", "where to watch", go)


def itunes_video() -> Dict[str, Any]:
    """Apple, the only service that ever looked like a first-party option.

    Asserts the FILTERED query works, because that is the part that broke. An unfiltered
    search still returns video rows, so a probe without the filter would pass while the
    thing we would actually use stays dead.
    """
    def go():
        r = requests.get("https://itunes.apple.com/search",
                         params={"term": "severance", "media": "tvShow",
                                 "entity": "tvSeason", "limit": 3},
                         headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        n = (r.json() or {}).get("resultCount", 0)
        if not n:
            return False, ("media=tvShow returns 0 — unchanged since 2026-10-13. "
                           "Video is still indexed but only reachable unfiltered, "
                           "where relevance is broken. Not usable.")
        return True, f"media=tvShow returned {n} results — Apple FIXED it, re-evaluate"
    return _probe("Apple iTunes Search (video)", "a first-party availability source", go)


def netflix_top10() -> Dict[str, Any]:
    """Not availability — a weekly popularity chart. Useful for Discover, not for
    'where can I watch this'. Probed because it moved host once already."""
    def go():
        r = requests.get("https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv",
                         headers=UA, timeout=TIMEOUT, stream=True)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code} (moved again?)"
        head = next(r.iter_lines(decode_unicode=True), "") or ""
        cols = head.split("\t")
        need = {"country_name", "week", "weekly_rank", "show_title"}
        missing = need - set(cols)
        if missing:
            return False, f"columns changed, missing {sorted(missing)}"
        return True, f"{len(cols)} columns, schema intact"
    return _probe("Netflix Top 10 feed", "Discover (popularity, not availability)", go)


def espn_scoreboard() -> Dict[str, Any]:
    """Sports. An undocumented public endpoint, so the most likely of all of these to
    change without notice."""
    def go():
        r = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
            headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        d = r.json() or {}
        if "events" not in d:
            return False, "200 but no 'events' key — shape changed"
        return True, f"{len(d.get('events') or [])} events"
    return _probe("ESPN scoreboard", "sports follows", go)


def check_all(tmdb_key: str) -> List[Dict[str, Any]]:
    """Every external dependency, in order of how much breaks without it."""
    return [
        tmdb_search(tmdb_key),
        tmdb_providers(tmdb_key),
        espn_scoreboard(),
        netflix_top10(),
        itunes_video(),
    ]
