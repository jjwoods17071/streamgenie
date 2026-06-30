"""
Per-user genre filters for Discover.

A user can hide whole genres (Kids, Reality, Anime) so they don't clutter the
discovery list — but it's OPT-IN per user (off by default), so people who like
these genres still find them.

Persists to the `genre_excludes` table when it exists (see
migrations/2026-06-29_genre_excludes.sql); always also tracks in session_state so
it works immediately even before the migration is run.
"""
import streamlit as st

# key -> (label, {TMDB tv genre ids}, requires_japanese_origin)
#   Kids    = TMDB genre 10762
#   Reality = TMDB genre 10764
#   Anime   = Animation (16) AND original language Japanese (TMDB has no "anime" genre)
EXCLUDABLE_GENRES = {
    "kids":    ("Kids",    {10762}, False),
    "reality": ("Reality", {10764}, False),
    "anime":   ("Anime",   {16},    True),
}


def _session_set() -> set:
    if "_genre_excludes" not in st.session_state:
        st.session_state["_genre_excludes"] = set()
    return st.session_state["_genre_excludes"]


@st.cache_data(ttl=300, show_spinner=False)
def _table_available(_client) -> bool:
    try:
        _client.table("genre_excludes").select("genre_key").limit(1).execute()
        return True
    except Exception:
        return False


def get_excluded(client, user_id) -> set:
    """The set of genre keys this user has chosen to hide."""
    keys = set(_session_set())
    if user_id and _table_available(client):
        try:
            r = client.table("genre_excludes").select("genre_key").eq("user_id", user_id).execute()
            keys |= {x["genre_key"] for x in (r.data or [])}
        except Exception:
            pass
    return keys & set(EXCLUDABLE_GENRES)


def set_excluded(client, user_id, keys) -> None:
    """Replace the user's excluded-genre set with `keys` (used by the profile toggles)."""
    keys = {k for k in keys if k in EXCLUDABLE_GENRES}
    st.session_state["_genre_excludes"] = set(keys)
    if not (user_id and _table_available(client)):
        return
    try:
        client.table("genre_excludes").delete().eq("user_id", user_id).execute()
        rows = [{"user_id": user_id, "genre_key": k} for k in keys]
        if rows:
            client.table("genre_excludes").upsert(rows, on_conflict="user_id,genre_key").execute()
    except Exception:
        pass


def exclude(client, user_id, key) -> None:
    """Add a single genre to the user's excludes (used by the per-show Discover button)."""
    if key not in EXCLUDABLE_GENRES:
        return
    cur = get_excluded(client, user_id)
    cur.add(key)
    set_excluded(client, user_id, cur)


def show_genre_keys(show) -> set:
    """Which excludable genre keys a Discover show matches (by genre_ids + language)."""
    gids = set(show.get("genre_ids") or [])
    lang = (show.get("original_language") or "").lower()
    out = set()
    for key, (_label, ids, need_ja) in EXCLUDABLE_GENRES.items():
        if gids & ids and (not need_ja or lang == "ja"):
            out.add(key)
    return out
