"""
Watchlist writes — add, update and remove a show for one user.

Extracted from app.py so the self-test can reach them. They were the only write paths it
couldn't: both read the signed-in user from `st.session_state`, so calling one outside a
Streamlit run was impossible and the app's most destructive operation had no coverage.

Taking `user_id` as an argument is also the first real step of the API extraction — a
phone client needs exactly this function, and it must not know what session state is.
Runtime-agnostic (no streamlit) — see ROADMAP.md on the module count.
"""
from typing import Any, Dict, List, Optional

import movies

TABLE = "shows"

# A show added from a list that doesn't say WHERE it streams carries one of these. They
# must never overwrite a real service name already on the row.
PLACEHOLDER_PROVIDERS = (None, "", "Multiple Providers")


def kind_of(tmdb_id: int, media_type: Optional[str] = None) -> str:
    """The media_type for a row, derived from the id unless stated.

    Sports follows are namespaced by NEGATIVE tmdb_id (sports.encode_id) — the same rule
    the media_type migration used to backfill them. Defaulting to a literal "tv" instead
    would mislabel every sports follow added from here on, and a mislabelled row is
    invisible to the surface that owns it.
    """
    if media_type:
        return media_type
    return "sports" if (tmdb_id or 0) < 0 else "tv"


def _scoped(q, client, user_id: str, tmdb_id: int, media_type: str):
    """Narrow a query to exactly one show for one user.

    (user_id, tmdb_id) is NOT enough: TMDB reuses ids across media types, which is the
    entire reason the media_type column exists — 550 is both Fight Club and an unrelated
    series. Leaving it out lets removing a show delete the film with the same id.
    """
    q = q.eq("user_id", user_id).eq("tmdb_id", tmdb_id)
    return q.eq("media_type", media_type) if movies.media_type_available(client) else q


def rows_for(client, user_id: str, tmdb_id: int,
             media_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every row this user has for this show, oldest first.

    Ownership is per (user_id, tmdb_id, media_type). The table permits several provider
    rows per show and that is how duplicates used to form, so every caller resolves
    through here rather than assuming one row exists.
    """
    q = _scoped(client.table(TABLE).select("id, provider_name, on_provider, created_at"),
                client, user_id, tmdb_id, kind_of(tmdb_id, media_type))
    return q.order("created_at").execute().data or []


def upsert(client, user_id: str, tmdb_id: int, title: str, region: str,
           on_provider: bool, next_air_date: Optional[str], overview: str,
           poster_path: Optional[str], provider_name: str,
           media_type: Optional[str] = None) -> str:
    """Add or update one show. Returns "added" or "updated".

    Invariant: ONE row per (user_id, tmdb_id, media_type), whatever the provider.
    """
    media_type = kind_of(tmdb_id, media_type)
    existing = rows_for(client, user_id, tmdb_id, media_type)
    data = {"user_id": user_id, "tmdb_id": tmdb_id, "title": title, "region": region,
            "on_provider": on_provider, "next_air_date": next_air_date,
            "overview": overview, "poster_path": poster_path,
            "provider_name": provider_name}
    if movies.media_type_available(client):
        # Explicit rather than trusting the column default: an add that relies on a
        # default is an add that changes meaning if the default ever does.
        data["media_type"] = media_type

    if existing:
        keeper = existing[0]                      # earliest row wins
        # Don't let a vaguer add degrade what we already know.
        if (provider_name in PLACEHOLDER_PROVIDERS
                and keeper.get("provider_name") not in PLACEHOLDER_PROVIDERS):
            data["provider_name"] = keeper["provider_name"]
        if not on_provider and keeper.get("on_provider"):
            data["on_provider"] = True
        client.table(TABLE).update(data).eq("id", keeper["id"]).execute()
        for extra in existing[1:]:                # converge legacy duplicates
            client.table(TABLE).delete().eq("id", extra["id"]).execute()
        return "updated"

    client.table(TABLE).insert(data).execute()
    # Imported here, not at module scope: show_status writes back through update_fields
    # below, so a top-level import would be a cycle.
    import show_status
    show_status.update_show_status(client, user_id, tmdb_id, title)
    return "added"


def delete(client, user_id: str, tmdb_id: int,
           media_type: Optional[str] = None) -> int:
    """Remove a show from this user's watchlist. Returns how many rows went.

    Scoped to (user_id, tmdb_id, media_type) — the same key upsert maintains.

    It used to match on region and provider_name instead, which was too NARROW:
    provider_name is nullable and the caller passed `row.get("provider_name", "Sports")`,
    which yields None for a NULL column because .get only falls back when the KEY is
    absent, and `.eq(col, None)` never matches SQL NULL. Remove did nothing, silently.

    Dropping those exposed the opposite error — too WIDE. Without media_type, removing a
    series would also delete the film sharing its TMDB id. Both are the same mistake:
    matching on a set of columns that isn't the identity of the thing.
    """
    q = _scoped(client.table(TABLE).delete(), client, user_id, tmdb_id,
                kind_of(tmdb_id, media_type))
    return len(q.execute().data or [])


def update_fields(client, user_id: str, tmdb_id: int, fields: Dict[str, Any],
                  media_type: Optional[str] = None) -> bool:
    """Update one show's columns. True if a row actually changed.

    The single update. Six surfaces used to write to `shows` directly, each with its own
    answer to "which columns identify a show" — that is why the same predicate existed in
    six forms and a fix in one never reached the others.
    """
    q = _scoped(client.table(TABLE).update(fields),
                client, user_id, tmdb_id, kind_of(tmdb_id, media_type))
    return bool(q.execute().data or [])


def set_provider(client, user_id: str, tmdb_id: int, provider_name: str,
                 media_type: Optional[str] = None) -> bool:
    """Record where a show streams. True if a row actually changed."""
    return update_fields(client, user_id, tmdb_id, {"provider_name": provider_name},
                         media_type)


def set_pinned(client, user_id: str, tmdb_id: int, value: bool,
               media_type: Optional[str] = None) -> bool:
    """Pin or unpin. True if a row actually changed."""
    return update_fields(client, user_id, tmdb_id, {"pinned": bool(value)}, media_type)


def set_next_air_date(client, user_id: str, tmdb_id: int, when: Optional[str],
                      media_type: Optional[str] = None) -> bool:
    """Write a refreshed air/streaming date. True if a row actually changed.

    Three copies of this update existed inline — for TV, for sports and for films — each
    with its own predicate, each wrapped in `except: pass`. The TV one carried the same
    over-narrow region/provider match as delete did, so it could match ZERO rows while
    raising nothing: the caller then set the new date on its in-memory dict, so the UI
    showed it, the database kept the old one, and TMDB was re-queried on every single run
    forever. A write that reports how many rows it touched cannot hide like that.
    """
    return update_fields(client, user_id, tmdb_id, {"next_air_date": when}, media_type)
