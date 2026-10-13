"""
Shared cache of shaped TMDB show records. Design, measurements and limits: SCALING.md.

Deliberately NOT a second entry point for show records. `tmdb.fetch_shows` stays the
only one; it takes an optional cache object and this module provides it. Two functions
that both answer "give me show records" is how this project's worst bugs have started
(CLAUDE.md section 3), and tmdb.py keeps no Supabase dependency this way.

Degrades to a no-op before the migration is run: `Store` reports nothing cached, writes
silently do nothing, and every caller falls through to TMDB exactly as it did before.
Runtime-agnostic (no streamlit).
"""
import datetime as dt
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cache
import observability

log = logging.getLogger(__name__)

TABLE = "show_cache"

# PostgREST puts .in_() ids in the URL, so a huge batch becomes a URL-length failure.
# 500 measured safe in SCALING.md.
READ_BATCH = 500

# Refresh by VOLATILITY, not on a blanket schedule. Of 25 shows sampled, 9 were Ended or
# Canceled — those records don't change, and refreshing them nightly is pure waste.
TIER_DAILY = dt.timedelta(days=1)       # returning, episode within 14 days
TIER_WEEKLY = dt.timedelta(days=7)      # returning, no date yet
TIER_MONTHLY = dt.timedelta(days=30)    # ended / canceled
_DEAD = {"ended", "canceled", "cancelled"}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@cache.memoize(ttl=300)
def table_available(_client) -> bool:
    """False until migrations/2026-10-12_show_cache.sql is run."""
    try:
        _client.table(TABLE).select("tmdb_id").limit(1).execute()
        return True
    except Exception:
        return False


def refresh_delay(payload: Dict[str, Any], now: Optional[dt.datetime] = None) -> dt.timedelta:
    """How long this record stays fresh, from its own content.

    A show that has ended will never change again; one with an episode next week changes
    constantly. Treating both the same is what makes a nightly refresh job scale badly.
    """
    status = (payload.get("status") or "").strip().lower()
    if status in _DEAD:
        return TIER_MONTHLY
    nxt = payload.get("next_episode_to_air") or {}
    when = nxt.get("air_date") if isinstance(nxt, dict) else None
    if when:
        try:
            air = dt.date.fromisoformat(str(when)[:10])
            days = (air - (now or _now()).date()).days
            if days <= 14:
                return TIER_DAILY
        except ValueError:
            pass
        return TIER_DAILY            # dated at all means it is moving
    return TIER_WEEKLY


class Store:
    """The cache object `tmdb.fetch_shows(ids, cache=...)` expects.

    Bound to one client and one media_type. Every method is failure-tolerant: a cache
    that errors must slow the app down, never break it.
    """

    def __init__(self, client, media_type: str = "tv"):
        self.client = client
        self.media_type = media_type

    def _ok(self) -> bool:
        return self.client is not None and table_available(self.client)

    def get_many(self, ids: Iterable[int],
                 allow_stale: bool = False) -> Dict[int, Dict[str, Any]]:
        """Cached records for these ids. FRESH ones only, by default.

        Returning only fresh rows means the cache self-heals even if the refresh cron
        never runs — an expired row is a miss, so the caller re-fetches it and writes it
        back. The cron then only reduces latency rather than being load-bearing.
        """
        ids = [int(i) for i in ids]
        if not ids or not self._ok():
            return {}
        out: Dict[int, Dict[str, Any]] = {}
        now_iso = _now().isoformat()
        for i in range(0, len(ids), READ_BATCH):
            chunk = ids[i:i + READ_BATCH]
            try:
                q = (self.client.table(TABLE).select("tmdb_id,payload,refresh_after")
                     .eq("media_type", self.media_type).in_("tmdb_id", chunk))
                if not allow_stale:
                    q = q.gt("refresh_after", now_iso)
                for row in q.execute().data or []:
                    if row.get("payload"):
                        out[int(row["tmdb_id"])] = row["payload"]
            except Exception as e:
                observability.capture(e, where="show_cache.get_many",
                                      batch=len(chunk))
                return out               # partial is fine; the rest become misses
        return out

    def put_many(self, records: Dict[int, Dict[str, Any]]) -> int:
        """Write shaped records back. Returns how many rows were sent."""
        if not records or not self._ok():
            return 0
        now = _now()
        rows = []
        for tmdb_id, payload in records.items():
            if not payload:
                continue
            rows.append({
                "tmdb_id": int(tmdb_id),
                "media_type": self.media_type,
                "payload": payload,
                "status": payload.get("status"),
                "fetched_at": now.isoformat(),
                "refresh_after": (now + refresh_delay(payload, now)).isoformat(),
            })
        if not rows:
            return 0
        try:
            self.client.table(TABLE).upsert(
                rows, on_conflict="tmdb_id,media_type").execute()
            return len(rows)
        except Exception as e:
            observability.capture(e, where="show_cache.put_many", rows=len(rows))
            return 0


def due_for_refresh(client, limit: int = 400,
                    media_type: str = "tv") -> List[int]:
    """Ids whose records have expired, oldest first."""
    if not (client is not None and table_available(client)):
        return []
    try:
        rows = (client.table(TABLE).select("tmdb_id")
                .eq("media_type", media_type)
                .lte("refresh_after", _now().isoformat())
                .order("refresh_after").limit(limit).execute().data or [])
        return [int(r["tmdb_id"]) for r in rows]
    except Exception as e:
        observability.capture(e, where="show_cache.due_for_refresh")
        return []


def refresh_due(client, fetch_fn, limit: int = 400, chunk: int = 40,
                budget_seconds: float = 480.0,
                media_type: str = "tv", log_fn=log.info) -> Dict[str, Any]:
    """Refresh expired records, oldest first, inside a wall-clock budget.

    Time-boxed and chunked ON PURPOSE. The job is never all-or-nothing: at any scale it
    refreshes what it can and resumes next run, so staleness grows gradually instead of
    the whole job timing out and refreshing nothing. The default budget is ~8 minutes of
    the cron's 15-minute ceiling.

    fetch_fn is injected (tmdb.fetch_shows) so this module needs no TMDB dependency and
    the test can drive it without network.
    """
    import time
    started = time.monotonic()
    ids = due_for_refresh(client, limit=limit, media_type=media_type)
    store = Store(client, media_type=media_type)
    done = failed = 0
    for i in range(0, len(ids), chunk):
        if time.monotonic() - started > budget_seconds:
            log_fn(f"show_cache: budget reached, {done} refreshed, "
                   f"{len(ids) - done - failed} left for next run")
            break
        batch = ids[i:i + chunk]
        try:
            records = fetch_fn(batch) or {}
            done += store.put_many(records)
            failed += len(batch) - len(records)
        except Exception as e:
            observability.capture(e, where="show_cache.refresh_due", batch=len(batch))
            failed += len(batch)
    return {"due": len(ids), "refreshed": done, "failed": failed,
            "seconds": round(time.monotonic() - started, 1)}


def stats(client, media_type: str = "tv") -> Dict[str, Any]:
    """Size and staleness, for the admin panel and the self-test."""
    if not (client is not None and table_available(client)):
        return {"available": False}
    try:
        total = (client.table(TABLE).select("tmdb_id", count="exact")
                 .eq("media_type", media_type).limit(1).execute().count or 0)
        stale = (client.table(TABLE).select("tmdb_id", count="exact")
                 .eq("media_type", media_type)
                 .lte("refresh_after", _now().isoformat()).limit(1).execute().count or 0)
        return {"available": True, "cached": total, "stale": stale}
    except Exception as e:
        observability.capture(e, where="show_cache.stats")
        return {"available": True, "cached": None, "stale": None}
