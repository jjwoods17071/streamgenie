"""
Genre CLASSIFICATION for Discover — which of Kids / Reality / Anime a show counts as.

The hides themselves live in filters.py (the `filter_prefs` table), which can also
suspend them. This module used to keep a second copy in a `genre_excludes` table that
was never actually created, so Discover's "hide this genre" button wrote into a
swallowed exception while every reader looked at filter_prefs. One preference, one
store.

Runtime-agnostic (no streamlit) — see ROADMAP.md on the module count.
"""

# key -> (label, {TMDB tv genre ids}, requires_japanese_origin)
#   Kids    = TMDB genre 10762
#   Reality = TMDB genre 10764
#   Anime   = Animation (16) AND original language Japanese (TMDB has no "anime" genre)
EXCLUDABLE_GENRES = {
    "kids":    ("Kids",    {10762}, False),
    "reality": ("Reality", {10764}, False),
    "anime":   ("Anime",   {16},    True),
}


def show_genre_keys(show) -> set:
    """Which excludable genre keys a Discover show matches (by genre_ids + language)."""
    gids = set(show.get("genre_ids") or [])
    lang = (show.get("original_language") or "").lower()
    out = set()
    for key, (_label, ids, need_ja) in EXCLUDABLE_GENRES.items():
        if gids & ids and (not need_ja or lang == "ja"):
            out.add(key)
    return out
