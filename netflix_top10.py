"""
Netflix's own weekly Top 10, as published by Netflix.

WHAT THIS IS AND IS NOT. A popularity chart: the ten most-watched titles per category per
week, with hours viewed, straight from Netflix. It is NOT an availability catalogue —
answering "what is everyone watching" and never "where can I watch this". It came out of
testing whether availability could be sourced per streaming service, and was the only
genuinely useful thing that did.

WHY IT IS WORTH HAVING: Discover's other rails are TMDB's global popularity, which is a
different question, computed differently. This is real viewing on the service holding 36
of the 89 titles in the library.

WHICH FILE, AND WHY. Netflix publishes two. The per-country file is 32 MB and sorted
COUNTRY then week, so reaching the US section means reading most of it. The global file
is 904 KB, sorted week-first newest-first, and carries hours_viewed and views, which the
country file does not. So: global file, streamed, stopped at the first week change —
about 2 KB of transfer. The trade is global figures instead of US ones, which is honest
to label and fine for a discovery rail.

Decoded as UTF-8 explicitly. requests' own charset guess mangles titles
("Schumacher '94" arrived as mojibake through iter_lines(decode_unicode=True)).

Attribution: data published by Netflix at netflix.com/tudum/top10. Credit it wherever it
is shown. Runtime-agnostic (no streamlit).
"""
import logging
from typing import Any, Dict, List

import requests

import cache
import observability

log = logging.getLogger(__name__)

URL = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"
CREDIT = "Netflix Top 10 (global), published weekly by Netflix"
_UA = {"User-Agent": "StreamGenie (non-commercial watchlist app)"}

# One week is 40 rows. A safety valve, not a target: if Netflix ever reorders the file
# oldest-first, this stops us streaming all 11,000 lines looking for a week change.
_MAX_LINES = 400

# Netflix splits every category by language. Collapsed into two rails, because the app
# already has a language filter and "TV (English)" is not a user-facing idea.
_TV = {"TV (English)", "TV (Non-English)"}
_FILM = {"Films (English)", "Films (Non-English)"}


def _empty() -> Dict[str, Any]:
    return {"week": None, "films": [], "tv": [], "credit": CREDIT}


def _int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


@cache.memoize(ttl=21600)
def fetch_week() -> Dict[str, Any]:
    """The most recent published week.

    Returns {"week", "films", "tv", "credit"}; empty on any failure, because a discovery
    rail is decoration and nothing here justifies a broken page.
    """
    rows: List[List[str]] = []
    try:
        with requests.get(URL, headers=_UA, timeout=45, stream=True) as r:
            r.raise_for_status()
            first_week = None
            seen = 0
            # Bytes, decoded by us — see the module docstring on mojibake.
            buf = b""
            for chunk in r.iter_content(chunk_size=8192):
                buf += chunk
                *complete, buf = buf.split(b"\n")
                done = False
                for raw in complete:
                    seen += 1
                    if seen == 1:
                        continue                      # header
                    if seen > _MAX_LINES:
                        done = True
                        break
                    f = raw.decode("utf-8", "replace").rstrip("\r").split("\t")
                    if len(f) < 6:
                        continue
                    if first_week is None:
                        first_week = f[0]
                    elif f[0] != first_week:
                        done = True
                        break
                    rows.append(f)
                if done:
                    break
    except Exception as e:
        observability.capture(e, where="netflix_top10.fetch_week")
        return _empty()

    if not rows:
        return _empty()

    def pick(cats: set) -> List[Dict[str, Any]]:
        out = []
        for f in rows:
            if f[1] not in cats:
                continue
            out.append({
                "rank": _int(f[2]),
                "title": f[3].strip(),
                "season": (f[4] or "").strip(),
                "hours_viewed": _int(f[5]),
                "views": _int(f[7]) if len(f) > 7 else 0,
                "weeks_charting": _int(f[8]) if len(f) > 8 else 0,
                "non_english": "Non-English" in f[1],
            })
        # Netflix ranks within each language split, so two #1s arrive. Order by actual
        # viewing instead, which is the only ranking that means anything once merged.
        return sorted(out, key=lambda x: -x["hours_viewed"])

    return {"week": rows[0][0], "films": pick(_FILM), "tv": pick(_TV), "credit": CREDIT}


def resolve(entries: List[Dict[str, Any]], match_fn,
            limit: int = 10) -> List[Dict[str, Any]]:
    """Attach TMDB matches so entries can show a poster and be added to the watchlist.

    match_fn is injected (discover.match_title) so this module needs no TMDB dependency.
    Netflix publishes titles as plain strings with no ids, so anything unmatched is kept
    rather than dropped — a chart entry without a poster is still information.
    """
    out = []
    for e in entries[:limit]:
        try:
            hit = match_fn(e["title"])
        except Exception:
            hit = None
        out.append({**e, "tmdb_id": (hit or {}).get("tmdb_id"),
                    "poster_path": (hit or {}).get("poster_path"),
                    "status": (hit or {}).get("status")})
    return out
