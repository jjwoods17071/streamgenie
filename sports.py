"""
Follow a sports team like a TV show — powered by ESPN's free public JSON API.
Supports NFL / MLB / NBA / NHL. Each team is stored in the watchlist with a NEGATIVE
tmdb_id that encodes BOTH the league and the ESPN team id, so teams flow through all
the existing card/nav/watchlist plumbing with no schema change. The app detects sports
rows by tmdb_id < 0. Games are the "episodes". 506sports has regional coverage maps.
"""
import datetime as dt
import requests
import streamlit as st

_UA = {"User-Agent": "Mozilla/5.0"}
_BASE = "https://site.api.espn.com/apis/site/v2/sports"
_OFFSET = 10_000_000  # league-id namespace size

# key -> (espn sport, espn league, label, league-index, 506sports coverage-map url)
LEAGUES = {
    "nfl":  ("football",   "nfl",  "🏈 NFL",  1, "https://506sports.com/nfl/index.php"),
    "mlb":  ("baseball",   "mlb",  "⚾ MLB",  2, "https://506sports.com/mlb.php"),
    "nba":  ("basketball", "nba",  "🏀 NBA",  3, "https://506sports.com/nba.php"),
    "nhl":  ("hockey",     "nhl",  "🏒 NHL",  4, "https://506sports.com/nhl.php"),
    "wnba": ("basketball", "wnba", "🏀 WNBA", 5, None),
}
_IDX_TO_LEAGUE = {v[3]: k for k, v in LEAGUES.items()}


def league_logo(league: str):
    lg = LEAGUES.get(league, (None, None))[1]
    return f"https://a.espncdn.com/i/teamlogos/leagues/500/{lg}.png" if lg else None


def encode_id(league: str, team_id) -> int:
    """Negative watchlist id that encodes league + ESPN team id."""
    return -(LEAGUES[league][3] * _OFFSET + int(team_id))


def decode_id(tmdb_id):
    """(league, team_id) from a negative sports id, or (None, None)."""
    try:
        aid = -int(tmdb_id)
        idx, team_id = divmod(aid, _OFFSET)
        return _IDX_TO_LEAGUE.get(idx), str(team_id)
    except Exception:
        return None, None


def is_sports_id(tmdb_id) -> bool:
    try:
        return int(tmdb_id) < 0
    except Exception:
        return False


def league_label(league: str) -> str:
    return LEAGUES.get(league, (None, None, "Sports", 0, None))[2]


def coverage_map_url(league: str):
    return LEAGUES.get(league, (None, None, None, None, None))[4]


@st.cache_data(ttl=86400, show_spinner=False)
def get_teams(league: str):
    """All teams in a league: {id, name, abbrev, logo}."""
    try:
        sp, lg = LEAGUES[league][0], LEAGUES[league][1]
        d = requests.get(f"{_BASE}/{sp}/{lg}/teams", headers=_UA, timeout=20).json()
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


def _logo(c):
    t = c.get("team") or {}
    if t.get("logos"):
        return (t["logos"][0] or {}).get("href")
    return t.get("logo")


@st.cache_data(ttl=3600, show_spinner=False)
def get_team_schedule(league: str, team_id: str):
    """A team's season schedule (oldest→newest) as a list of game dicts."""
    try:
        sp, lg = LEAGUES[league][0], LEAGUES[league][1]
        d = requests.get(f"{_BASE}/{sp}/{lg}/teams/{team_id}/schedule", headers=_UA, timeout=20).json()
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
                "home_logo": _logo(home),
                "away_logo": _logo(away),
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


def record(games, team_name):
    """W-L from completed games for the followed team."""
    w = l = 0
    for g in games:
        if g.get("completed") and g.get("home_score") not in (None, "") and g.get("away_score") not in (None, ""):
            try:
                hs, as_ = float(g["home_score"]), float(g["away_score"])
            except Exception:
                continue
            ours, theirs = (hs, as_) if g.get("home") == team_name else (as_, hs)
            if ours > theirs:
                w += 1
            elif ours < theirs:
                l += 1
    return w, l
