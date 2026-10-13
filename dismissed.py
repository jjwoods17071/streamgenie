"""
Dismissed ("Not Interested") shows for the discovery carousels.

Persists to the `dismissed_shows` table. Filtering the New/Trending/Top-Rated lists hides
anything dismissed.

The optimistic "hide it immediately" set used to live in st.session_state in here, which
made this module unimportable outside Streamlit. It now belongs to the caller and arrives
as `also` — the module answers what the DATABASE knows, the UI owns what this session
believes. Same behaviour, and the caller was already the only thing that could usefully
own it (see ROADMAP.md on the module count).
"""
from typing import Iterable, Optional, Set

import cache


@cache.memoize(ttl=300)
def table_available(_client) -> bool:
    """True if the dismissed_shows table exists. Leading _ keeps the client out of the key."""
    try:
        _client.table("dismissed_shows").select("tmdb_id").limit(1).execute()
        return True
    except Exception:
        return False


def get_dismissed(client, user_id, also: Optional[Iterable[int]] = None) -> Set[int]:
    """Every tmdb_id this user has hidden, plus anything in `also`.

    `also` is the caller's optimistic set — shows dismissed in this session that may not
    have reached the database yet.
    """
    ids = set(also or ())
    if user_id and table_available(client):
        try:
            r = (client.table("dismissed_shows").select("tmdb_id")
                 .eq("user_id", user_id).execute())
            ids |= {x["tmdb_id"] for x in (r.data or [])}
        except Exception:
            pass
    return ids


def dismiss(client, user_id, tmdb_id) -> bool:
    """Hide a show from Discover. True if it will still be hidden after a reload.

    Returns the database result rather than swallowing it: the caller hides the show
    either way, so this is the only way to tell "hidden" from "hidden until you refresh".
    """
    if not (user_id and table_available(client)):
        return False
    try:
        client.table("dismissed_shows").upsert(
            {"user_id": user_id, "tmdb_id": tmdb_id}, on_conflict="user_id,tmdb_id"
        ).execute()
        return True
    except Exception:
        return False
