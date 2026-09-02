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

import show_status

TABLE = "shows"

# A show added from a list that doesn't say WHERE it streams carries one of these. They
# must never overwrite a real service name already on the row.
PLACEHOLDER_PROVIDERS = (None, "", "Multiple Providers")


def rows_for(client, user_id: str, tmdb_id: int) -> List[Dict[str, Any]]:
    """Every row this user has for this show, oldest first.

    Ownership is per (user_id, tmdb_id). The table permits several provider rows per show
    and that is how duplicates used to form, so every caller resolves through here rather
    than assuming one row exists.
    """
    return (client.table(TABLE)
            .select("id, provider_name, on_provider, created_at")
            .eq("user_id", user_id).eq("tmdb_id", tmdb_id)
            .order("created_at").execute().data or [])


def upsert(client, user_id: str, tmdb_id: int, title: str, region: str,
           on_provider: bool, next_air_date: Optional[str], overview: str,
           poster_path: Optional[str], provider_name: str) -> str:
    """Add or update one show. Returns "added" or "updated".

    Invariant: ONE row per (user_id, tmdb_id), whatever the provider.
    """
    existing = rows_for(client, user_id, tmdb_id)
    data = {"user_id": user_id, "tmdb_id": tmdb_id, "title": title, "region": region,
            "on_provider": on_provider, "next_air_date": next_air_date,
            "overview": overview, "poster_path": poster_path,
            "provider_name": provider_name}

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
    show_status.update_show_status(client, user_id, tmdb_id, title)
    return "added"


def delete(client, user_id: str, tmdb_id: int) -> int:
    """Remove a show from this user's watchlist. Returns how many rows went.

    Matches on (user_id, tmdb_id) ONLY. It used to also require region and provider_name,
    which contradicted the upsert invariant. provider_name is nullable and the caller
    passed `row.get("provider_name", "Sports")` — which yields None for a NULL column,
    because .get only falls back when the KEY is absent — and `.eq(col, None)` never
    matches SQL NULL. So Remove did nothing, silently, while looking like it worked.

    No row in the data has a NULL provider today, so this was latent rather than live.
    The predicate should still state the invariant instead of happening to agree with it.
    """
    gone = (client.table(TABLE).delete()
            .eq("user_id", user_id).eq("tmdb_id", tmdb_id)
            .execute().data or [])
    return len(gone)
