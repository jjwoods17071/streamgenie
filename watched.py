"""
Watched-episode tracking. Stores which episodes a user has marked watched in the
`watched_episodes` table (created by add_watched_episodes_table.sql).

All functions degrade gracefully (return empty / False) if the table doesn't exist
yet, so the UI can ship before the migration is run.
"""
from collections import Counter
from typing import Set, Tuple, Dict

import streamlit as st


@st.cache_data(ttl=300, show_spinner=False)
def table_available(_client) -> bool:
    """True if the watched_episodes table exists (cached 5 min). Leading _ skips hashing the client."""
    try:
        _client.table("watched_episodes").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def get_watched(client, user_id: str, tmdb_id: int) -> Set[Tuple[int, int]]:
    """Set of (season_number, episode_number) the user has marked watched for a show."""
    try:
        r = client.table("watched_episodes")\
            .select("season_number,episode_number")\
            .eq("user_id", user_id).eq("tmdb_id", tmdb_id).execute()
        return {(x["season_number"], x["episode_number"]) for x in (r.data or [])}
    except Exception:
        return set()


def set_watched(client, user_id: str, tmdb_id: int, season: int, episode: int, watched: bool) -> bool:
    """Mark (watched=True) or unmark (False) a single episode."""
    try:
        if watched:
            client.table("watched_episodes").upsert(
                {"user_id": user_id, "tmdb_id": tmdb_id,
                 "season_number": season, "episode_number": episode},
                on_conflict="user_id,tmdb_id,season_number,episode_number"
            ).execute()
        else:
            client.table("watched_episodes").delete()\
                .eq("user_id", user_id).eq("tmdb_id", tmdb_id)\
                .eq("season_number", season).eq("episode_number", episode).execute()
        return True
    except Exception:
        return False


def set_season(client, user_id: str, tmdb_id: int, season: int,
               episode_numbers, watched: bool) -> bool:
    """Mark/unmark a whole season at once."""
    try:
        if watched:
            rows = [{"user_id": user_id, "tmdb_id": tmdb_id,
                     "season_number": season, "episode_number": en} for en in episode_numbers]
            if rows:
                client.table("watched_episodes").upsert(
                    rows, on_conflict="user_id,tmdb_id,season_number,episode_number"
                ).execute()
        else:
            client.table("watched_episodes").delete()\
                .eq("user_id", user_id).eq("tmdb_id", tmdb_id)\
                .eq("season_number", season).execute()
        return True
    except Exception:
        return False


def watched_counts(client, user_id: str) -> Dict[int, int]:
    """tmdb_id -> number of watched episodes for the user (for card badges, catch-up and
    the watchlist's caught-up/history grouping). Pages past Supabase's 1000-row response
    cap — without this, users with large histories are undercounted and fully-watched
    shows wrongly look 'behind' (e.g. a 40-episode show counted as 32)."""
    try:
        counts: Counter = Counter()
        start, page = 0, 1000
        while True:
            r = (client.table("watched_episodes").select("tmdb_id")
                 .eq("user_id", user_id).range(start, start + page - 1).execute())
            batch = r.data or []
            counts.update(x["tmdb_id"] for x in batch)
            if len(batch) < page:
                break
            start += page
        return dict(counts)
    except Exception:
        return {}
