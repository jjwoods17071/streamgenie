"""
User filters that can be SUSPENDED, not just switched off.

"Hide kids' content" is right 360 days a year and wrong the evening a niece visits. Every
streaming service models preferences as permanent, so your only options are to live with
the wrong result or turn the filter off and forget to turn it back on. A suspension has an
expiry, so the filter returns without anyone remembering.

Runtime-agnostic (no streamlit) so the future API and the self-test can both use it —
see ROADMAP.md on getting the module count from 7/12 to 12/12.
"""
import datetime as dt
from typing import Any, Dict, Optional

TABLE = "filter_prefs"

# key -> (label, help). Genre keys mirror genre_prefs.EXCLUDABLE_GENRES.
FILTERS = {
    "genre:kids":    ("Hide kids' content", "Cartoons and children's programming"),
    "genre:reality": ("Hide reality TV", "Competition and reality formats"),
    "genre:anime":   ("Hide anime", "Japanese animation"),
}

# Suspension presets. "tonight" ends at 6am so an evening's viewing isn't cut off at
# midnight; the rest are plain durations.
def _tomorrow_6am(now: dt.datetime) -> dt.datetime:
    nxt = (now + dt.timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    return nxt


SUSPEND_PRESETS = {
    "For tonight": _tomorrow_6am,
    "For 3 days": lambda now: now + dt.timedelta(days=3),
    "For a week": lambda now: now + dt.timedelta(days=7),
}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def table_available(client) -> bool:
    """False until migrations/2026-09-02_filter_prefs.sql is run. Callers fall back to
    session-only state so the UI still works, exactly as genre_prefs did before."""
    try:
        client.table(TABLE).select("filter_key").limit(1).execute()
        return True
    except Exception:
        return False


def get_state(client, user_id: str) -> Dict[str, Dict[str, Any]]:
    """{filter_key: {enabled, suspended_until, value}} for every stored filter."""
    try:
        rows = (client.table(TABLE)
                .select("filter_key,enabled,value,suspended_until")
                .eq("user_id", user_id).execute().data or [])
    except Exception:
        return {}
    return {r["filter_key"]: {"enabled": bool(r.get("enabled")),
                             "value": r.get("value"),
                             "suspended_until": r.get("suspended_until")}
            for r in rows}


def _parse(ts) -> Optional[dt.datetime]:
    if not ts:
        return None
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def is_suspended(entry: Dict[str, Any], now: Optional[dt.datetime] = None) -> bool:
    """True while a suspension is still running. A PAST timestamp means it expired and the
    filter is back in force — that self-healing is the whole point."""
    until = _parse((entry or {}).get("suspended_until"))
    return bool(until and until > (now or _now()))


def active_keys(state: Dict[str, Dict[str, Any]], now: Optional[dt.datetime] = None) -> set:
    """Filters currently in force: enabled AND not under a live suspension."""
    return {k for k, v in (state or {}).items()
            if v.get("enabled") and not is_suspended(v, now)}


def suspended_keys(state: Dict[str, Dict[str, Any]], now: Optional[dt.datetime] = None) -> set:
    return {k for k, v in (state or {}).items()
            if v.get("enabled") and is_suspended(v, now)}


def describe_suspension(entry: Dict[str, Any], now: Optional[dt.datetime] = None) -> str:
    """'resumes Thu 06:00' — a suspended filter must SAY so. Silently changing what a
    user sees is how a filter stops being trusted."""
    until = _parse((entry or {}).get("suspended_until"))
    if not until:
        return ""
    now = now or _now()
    delta = until - now
    if delta.total_seconds() <= 0:
        return ""
    if delta < dt.timedelta(hours=24):
        return f"resumes {until.astimezone().strftime('%H:%M')}"
    return f"resumes {until.astimezone().strftime('%a %d %b')}"


def set_enabled(client, user_id: str, key: str, enabled: bool) -> bool:
    return _upsert(client, user_id, key, {"enabled": enabled, "suspended_until": None})


def suspend(client, user_id: str, key: str, until: dt.datetime) -> bool:
    return _upsert(client, user_id, key, {"enabled": True,
                                          "suspended_until": until.isoformat()})


def resume(client, user_id: str, key: str) -> bool:
    """End a suspension early — the filter comes straight back."""
    return _upsert(client, user_id, key, {"suspended_until": None})


def _upsert(client, user_id: str, key: str, fields: Dict[str, Any]) -> bool:
    try:
        row = {"user_id": user_id, "filter_key": key,
               "updated_at": _now().isoformat(), **fields}
        client.table(TABLE).upsert(row, on_conflict="user_id,filter_key").execute()
        return True
    except Exception:
        return False


# ---------------- subscriptions ----------------
# Which services the user actually pays for. Everything else in this app answers "where
# does this stream?"; this is what turns that into "can I watch it?".

SUBSCRIPTIONS_KEY = "services:subscribed"


def get_subscriptions(client, user_id: str) -> list:
    """Services the user says they have. Empty list = never answered, which is NOT the
    same as "subscribes to nothing" — callers must treat unknown as "don't gate anything",
    or a user who skipped the question would see their whole library greyed out.
    """
    try:
        rows = (client.table(TABLE).select("value")
                .eq("user_id", user_id).eq("filter_key", SUBSCRIPTIONS_KEY)
                .execute().data or [])
    except Exception:
        return []
    val = (rows[0].get("value") if rows else None) or []
    return [str(v) for v in val] if isinstance(val, list) else []


def set_subscriptions(client, user_id: str, services) -> bool:
    return _upsert(client, user_id, SUBSCRIPTIONS_KEY,
                   {"enabled": True, "value": sorted(set(services))})


def has_answered(client, user_id: str) -> bool:
    """True once the user has answered at all — including answering "none of these"."""
    try:
        rows = (client.table(TABLE).select("filter_key")
                .eq("user_id", user_id).eq("filter_key", SUBSCRIPTIONS_KEY)
                .execute().data or [])
        return bool(rows)
    except Exception:
        return False
