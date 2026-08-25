"""
Season/series milestone classification — premieres, finales, and "returning but undated".

The premiere/finale rules used to live inline in newsletter.build_sections, so a season
premiere was called out once a week by email while the app rendered it as plain "S3E1",
visually identical to "S2E7 airs Tuesday". This module is the single source of truth for
both, the way recs.py is for recommendations.

Runtime-agnostic (no streamlit import) so the headless cron/newsletter path can use it.
"""
from typing import Any, Dict, Optional

# A show TMDB still expects to continue. "Returning Series" is the reliable signal;
# in_production covers shows between seasons that TMDB hasn't re-flagged yet.
RETURNING_STATUSES = {"Returning Series"}
ENDED_STATUSES = {"Ended", "Canceled", "Cancelled"}

# kind -> (badge emoji, sort weight). Premieres outrank finales because "a new season
# starts" is the moment users are actually waiting for.
KIND_BADGE = {
    "series_premiere": ("🎬", 0),
    "season_premiere": ("🎬", 1),
    "series_finale":   ("🏁", 2),
    "season_finale":   ("🏁", 3),
    "mid_season":      ("⏸", 4),
}

PREMIERE_KINDS = {"series_premiere", "season_premiere"}


def classify(next_ep: Optional[Dict[str, Any]],
             show_status: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Classify a TMDB next_episode_to_air into a milestone, or None if it's a normal one.

    Returns {"kind", "tag", "season", "badge"}. `show_status` is the TMDB series status
    and only matters for finales — it decides "Season 4 finale" vs "Series finale".
    """
    if not isinstance(next_ep, dict) or not next_ep.get("air_date"):
        return None

    season = next_ep.get("season_number")
    etype = (next_ep.get("episode_type") or "").lower()
    kind = tag = None

    # Episode 1 of any season is a premiere — TMDB's episode_type is inconsistent about
    # marking these, so the episode number is the more reliable signal.
    if next_ep.get("episode_number") == 1 or etype == "premiere":
        if season == 1:
            kind, tag = "series_premiere", "Series premiere"
        elif season:
            kind, tag = "season_premiere", f"Season {season} premiere"

    # A finale claim wins over the premiere check — a one-episode season is a finale.
    if etype == "finale":
        if (show_status or "") in ENDED_STATUSES:
            kind, tag = "series_finale", "Series finale"
        else:
            kind, tag = "season_finale", f"Season {season} finale" if season else "Season finale"
    elif etype == "mid_season" and not kind:
        kind, tag = "mid_season", "Mid-season finale"

    if not kind:
        return None
    badge, _ = KIND_BADGE.get(kind, ("✨", 9))
    return {"kind": kind, "tag": tag, "season": season, "badge": badge}


def is_premiere(milestone: Optional[Dict[str, Any]]) -> bool:
    """True when this milestone is a new season starting (the headline moment)."""
    return bool(milestone) and milestone.get("kind") in PREMIERE_KINDS


def sort_weight(milestone: Optional[Dict[str, Any]]) -> int:
    """Ordering weight — premieres first, plain episodes last."""
    if not milestone:
        return 9
    return KIND_BADGE.get(milestone.get("kind"), ("", 9))[1]


def is_returning_undated(meta: Dict[str, Any]) -> bool:
    """True for a show that's coming back but has no announced date yet.

    These are invisible today: the app's upcoming agenda only lists shows with a
    next_air_date, and the newsletter only covers the next 7 days — so a renewed show
    silently disappears from view until TMDB publishes a date, which is exactly when
    users start asking "is it cancelled?".
    """
    if not isinstance(meta, dict) or not meta:
        return False
    if (meta.get("next_episode_to_air") or {}).get("air_date"):
        return False           # it has a date; it belongs in the normal agenda
    status = meta.get("status") or ""
    if status in ENDED_STATUSES:
        return False
    return status in RETURNING_STATUSES or bool(meta.get("in_production"))
