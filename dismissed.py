"""
Dismissed (\"Not Interested\") shows for the discovery carousels.

Persists to the `dismissed_shows` table when it exists (add_dismissed_shows_table.sql);
always also tracks in session_state so it works immediately even before the table
is created. Filtering the New/Trending/Top-Rated lists hides anything dismissed.
"""
import streamlit as st


def _session_set():
    if "_dismissed" not in st.session_state:
        st.session_state["_dismissed"] = set()
    return st.session_state["_dismissed"]


@st.cache_data(ttl=300, show_spinner=False)
def _table_available(_client) -> bool:
    try:
        _client.table("dismissed_shows").select("tmdb_id").limit(1).execute()
        return True
    except Exception:
        return False


def get_dismissed(client, user_id) -> set:
    ids = set(_session_set())
    if user_id and _table_available(client):
        try:
            r = client.table("dismissed_shows").select("tmdb_id").eq("user_id", user_id).execute()
            ids |= {x["tmdb_id"] for x in (r.data or [])}
        except Exception:
            pass
    return ids


def dismiss(client, user_id, tmdb_id):
    _session_set().add(tmdb_id)
    if user_id and _table_available(client):
        try:
            client.table("dismissed_shows").upsert(
                {"user_id": user_id, "tmdb_id": tmdb_id}, on_conflict="user_id,tmdb_id"
            ).execute()
        except Exception:
            pass
