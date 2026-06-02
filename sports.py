"""
Follow an NFL team like a TV show — powered by ESPN's free public JSON API.
Each team is stored in the watchlist with a NEGATIVE tmdb_id ( = -espn_team_id ) so it
flows through all the existing plumbing (cards, ?show= nav, watchlist) without a schema
change; the app detects sports rows by tmdb_id < 0. Games are the "episodes".
506sports provides regional CBS/Fox coverage maps (image-based) we link out to.
"""
import datetime as dt
import requests
import streamlit as st

_UA = {"User-Agent": "Mozilla/5.0"}
_ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"

# 506sports NFL regional coverage maps (which CBS/Fox game your market gets)
COVERAGE_MAP_URL = "https://506sports.com/nfl/index.php"


def is_sports_id(tmdb_id) -> bool:
    try:
        return int(tmdb_id) < 0
    except Exception:
        return False


def espn_team_id(tmdb_id) -> str:
    return str(-int(tmdb_id))


@st.cache_data(ttl=86400, show_spinner=False)
def get_nfl_teams():
    """All 32 NFL teams: {id, name, abbrev, logo}."""
    try:
        d = requests.get(f"{_ESPN}/teams", headers=_UA, timeout=20).json()
        teams = d["sports"][0]["leagues"][0]["teams"]
        out = []
        for x in teams:
            t = x["team"]
            logo = (t.get("logos") or [{}])[0].get("href")
            out.append({"id": str(t["id"]), "name": t.get("displayName"),
                        "abbrev": t.get("abbreviation"), "logo": logo})
        return sorted(out, key=lambda z: z["name"] or "")
    except Exception:
        return []


def _score(c):
    s = c.get("score")
    if isinstance(s, dict):
        return s.get("displayValue") or s.get("value")
    return s


@st.cache_data(ttl=3600, show_spinner=False)
def get_team_schedule(team_id: str):
    """A team's season schedule as a list of games (oldest→newest)."""
    try:
        d = requests.get(f"{_ESPN}/teams/{team_id}/schedule", headers=_UA, timeout=20).json()
        games = []
        for e in d.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            cs = comp.get("competitors", [])
            home = next((c for c in cs if c.get("homeAway") == "home"), {})
            away = next((c for c in cs if c.get("homeAway") == "away"), {})
            stype = ((comp.get("status") or {}).get("type")
                     or (e.get("status") or {}).get("type") or {})
            bc = comp.get("broadcasts") or []
            net = ", ".join(bc[0].get("names", [])) if bc else ""
            wk = e.get("week") or {}
            games.append({
                "date": (e.get("date") or "")[:10],
                "datetime": e.get("date") or "",
                "home": (home.get("team") or {}).get("displayName"),
                "away": (away.get("team") or {}).get("displayName"),
                "home_abbr": (home.get("team") or {}).get("abbreviation"),
                "away_abbr": (away.get("team") or {}).get("abbreviation"),
                "home_logo": (home.get("team") or {}).get("logos", [{}])[0].get("href") if (home.get("team") or {}).get("logos") else None,
                "home_score": _score(home),
                "away_score": _score(away),
                "status": stype.get("description") or stype.get("name"),
                "completed": bool(stype.get("completed")),
                "network": net,
                "week": wk.get("number") or wk.get("text"),
            })
        games.sort(key=lambda g: g["datetime"] or "")
        return games
    except Exception:
        return []


def next_game(games):
    today = dt.date.today().isoformat()
    up = [g for g in games if (g.get("date") or "") >= today and not g.get("completed")]
    return up[0] if up else None


def team_record(games):
    """W-L from completed games where we can tell (uses score compare only when both present)."""
    w = l = 0
    for g in games:
        if g.get("completed") and g.get("home_score") not in (None, "") and g.get("away_score") not in (None, ""):
            try:
                hs, as_ = float(g["home_score"]), float(g["away_score"])
                # we don't know which side is "our" team here; record computed in app where team known
            except Exception:
                pass
    return None  # record computed in the app layer where the followed team is known
