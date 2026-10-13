"""
StreamGenie HTTP API — the layer a phone talks to.

WHY THIS EXISTS (ROADMAP.md, NEAR item 2): the modules beside this file are already
UI-agnostic, but nothing has ever consumed them except app.py. Standing this up with
Streamlit still the only consumer is how we find out whether the boundary is right
BEFORE betting a native client on it. If pointing the existing UI at these endpoints
hurts, the API is wrong.

WHAT IT IS FOR, specifically. A phone does NOT need this for watchlist CRUD — with RLS
verified (2026-10-12) it can talk to Supabase directly with the anon key plus the user's
JWT, and the database refuses everyone else's rows. This API exists for the things only
Python can do, and for the one thing a client must never hold:

  * the TMDB key. It is read by 18 files server-side and must never ship in an app
    binary, so every TMDB call a client needs is proxied here.
  * recommendations, taste signals, release lookups, milestone classification — real
    logic, in modules, that a client should not reimplement.

AUTH. Bearer token = the user's Supabase JWT, obtained by the client from Supabase's own
SDK. We verify it with Supabase rather than holding a signing secret, then hand the
modules a client authenticated AS THAT USER — so RLS is a second line of defence. If a
handler ever passes the wrong user_id, the database still refuses. That is the whole
point of having verified RLS, and it is why this does not run on the service key.

RUNNING IT
    pip install -r requirements-api.txt
    uvicorn api:app --reload --port 8000
Deployment is NOT solved: Streamlit Cloud hosts one process, so this needs its own home
(Railway/Fly/Render) before a client can use it. Deliberately out of scope here.
"""
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from supabase import create_client

import filters
import milestones
import movies
import recs
import tmdb
import watchlist

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
REGION = os.getenv("TMDB_REGION", "US").strip() or "US"

app = FastAPI(
    title="StreamGenie API",
    version="0.1.0",
    description="What do I watch tonight, and where is it?",
)


# ---------------------------------------------------------------- auth

def _anon():
    if not (SUPABASE_URL and ANON_KEY):
        raise HTTPException(503, "SUPABASE_URL / SUPABASE_ANON_KEY not configured")
    return create_client(SUPABASE_URL, ANON_KEY)


class Caller:
    """A verified user and a database client scoped to them."""

    def __init__(self, user_id: str, client):
        self.user_id = user_id
        self.client = client


def caller(authorization: Optional[str] = Header(None)) -> Caller:
    """Verify the bearer token and return a client acting as that user.

    Verified by asking Supabase, not by checking a signature locally: holding the JWT
    secret here would be a second place for it to leak, and the round trip buys
    revocation for free — a signed-out token stops working immediately.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authorization: Bearer <supabase jwt> required")
    token = authorization.split(" ", 1)[1].strip()
    client = _anon()
    try:
        who = client.auth.get_user(token)
    except Exception:
        raise HTTPException(401, "token rejected by Supabase")
    user = getattr(who, "user", None)
    if not user or not getattr(user, "id", None):
        raise HTTPException(401, "token carries no user")
    # Act as the user from here on, so RLS backs up every handler.
    try:
        client.postgrest.auth(token)
    except Exception:
        raise HTTPException(500, "could not scope the database client to the user")
    return Caller(user.id, client)


# ---------------------------------------------------------------- shapes

class ShowIn(BaseModel):
    tmdb_id: int
    title: str
    provider_name: str = "Multiple Providers"
    region: str = REGION
    on_provider: bool = True
    next_air_date: Optional[str] = None
    overview: str = ""
    poster_path: Optional[str] = None


# ---------------------------------------------------------------- routes

@app.get("/health")
def health() -> Dict[str, Any]:
    """Unauthenticated, and deliberately says nothing about the data."""
    return {"ok": True, "supabase": bool(SUPABASE_URL and ANON_KEY)}


@app.get("/me")
def me(c: Caller = Depends(caller)) -> Dict[str, str]:
    return {"user_id": c.user_id}


@app.get("/watchlist")
def get_watchlist(c: Caller = Depends(caller)) -> List[Dict[str, Any]]:
    """The TV + sports watchlist. Movies have their own route, as in the UI — mixing
    them is what used to send a movie id to /tv/{id} and 404."""
    return movies.fetch_tv_rows(c.client, c.user_id, watchlist.COLUMNS)


@app.post("/watchlist", status_code=201)
def add_to_watchlist(show: ShowIn, c: Caller = Depends(caller)) -> Dict[str, str]:
    result = watchlist.upsert(
        c.client, c.user_id, show.tmdb_id, show.title, show.region, show.on_provider,
        show.next_air_date, show.overview, show.poster_path, show.provider_name)
    return {"result": result}


@app.delete("/watchlist/{tmdb_id}")
def remove_from_watchlist(tmdb_id: int,
                          c: Caller = Depends(caller)) -> Dict[str, int]:
    removed = watchlist.delete(c.client, c.user_id, tmdb_id)
    if not removed:
        raise HTTPException(404, "not on your watchlist")
    return {"removed": removed}


@app.get("/movies")
def get_movies(c: Caller = Depends(caller)) -> List[Dict[str, Any]]:
    return movies.list_movies(c.client, c.user_id)


@app.get("/movies/{tmdb_id}/release")
def movie_release(tmdb_id: int, region: str = REGION,
                  c: Caller = Depends(caller)) -> Dict[str, Any]:
    """When does this film reach a service? The question no competitor answers."""
    return movies.release_info(tmdb_id, region)


@app.get("/recommendations")
def recommendations(limit: int = Query(6, ge=1, le=24),
                    c: Caller = Depends(caller)) -> Dict[str, Any]:
    """Taste-based picks. use_genie=False keeps a model call off the request path —
    a client asking for recommendations should not wait on an LLM, and the UI's
    cached path is where that belongs."""
    state = filters.get_state(c.client, c.user_id)
    hidden = {k.split(":", 1)[1] for k in filters.active_keys(state)
              if k.startswith("genre:")}
    return recs.for_user(c.client, c.user_id, limit=limit,
                         excluded_genres=hidden, use_genie=False)


@app.get("/taste")
def taste(c: Caller = Depends(caller)) -> Dict[str, Any]:
    return recs.taste_signals(c.client, c.user_id)


@app.get("/filters")
def get_filters(c: Caller = Depends(caller)) -> Dict[str, Any]:
    state = filters.get_state(c.client, c.user_id)
    return {
        "state": state,
        "active": sorted(filters.active_keys(state)),
        "suspended": sorted(filters.suspended_keys(state)),
        "subscriptions": filters.get_subscriptions(c.client, c.user_id),
    }


@app.get("/search")
def search(q: str = Query(..., min_length=1), kind: str = Query("tv"),
           c: Caller = Depends(caller)) -> List[Dict[str, Any]]:
    """TMDB search, proxied. The reason this route exists at all: the API key stays
    here and never reaches a client."""
    if kind == "movie":
        return movies.search(q)
    if kind != "tv":
        raise HTTPException(400, "kind must be 'tv' or 'movie'")
    data = tmdb.get("/search/tv", {"query": q}) or {}
    return [{"tmdb_id": r.get("id"), "title": r.get("name"),
             "year": (r.get("first_air_date") or "")[:4],
             "poster_path": r.get("poster_path"),
             "overview": r.get("overview") or ""}
            for r in (data.get("results") or [])[:10]]


@app.get("/shows/{tmdb_id}/milestone")
def milestone(tmdb_id: int, c: Caller = Depends(caller)) -> Dict[str, Any]:
    """Premiere / finale / 'returning but undated' for one show."""
    details = tmdb.get(f"/tv/{tmdb_id}") or {}
    if not details:
        raise HTTPException(404, "unknown show")
    return {
        "tmdb_id": tmdb_id,
        "title": details.get("name"),
        "seasons": milestones.real_season_count(details),
        "milestone": milestones.classify(details.get("next_episode_to_air"),
                                         details.get("status")),
    }
