"""
Follow a sports team like a TV show — powered by ESPN's free public JSON API.
Supports NFL / MLB / NBA / NHL. Each team is stored in the watchlist with a NEGATIVE
tmdb_id that encodes BOTH the league and the ESPN team id, so teams flow through all
the existing card/nav/watchlist plumbing with no schema change. The app detects sports
rows by tmdb_id < 0. Games are the "episodes". 506sports has regional coverage maps.
"""
import datetime as dt
import re
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
    "epl":  ("soccer", "eng.1",           "⚽ EPL", 6, None),
    "ucl":  ("soccer", "uefa.champions",  "⚽ UCL", 7, None),
    "mls":  ("soccer", "usa.1",           "⚽ MLS", 8, None),
    "wc":   ("soccer", "fifa.world",      "🌍 World Cup", 9, None),
    "cfb":  ("football",   "college-football",         "🏈 College FB", 10, None),
    "cbb":  ("basketball", "mens-college-basketball",  "🏀 College BB", 11, None),
    # Event-model series: you follow the whole series, "episodes" are races/tournaments/cards.
    "f1":   ("racing", "f1",   "🏎️ F1",        12, None),
    "golf": ("golf",   "pga",  "⛳ PGA Tour",   13, None),
    "ufc":  ("mma",    "ufc",  "🥊 UFC",        14, None),
    "atp":  ("tennis", "atp",  "🎾 ATP",        15, None),
    "wta":  ("tennis", "wta",  "🎾 WTA",        16, None),
}
SOCCER = {"epl", "ucl", "mls", "wc"}      # leagues that can draw → W-D-L records
EVENT = {"f1", "golf", "ufc", "atp", "wta"}   # series, not head-to-head teams
SEASON_CAL = {"f1", "golf", "ufc"}        # event leagues with a labeled season calendar
_IDX_TO_LEAGUE = {v[3]: k for k, v in LEAGUES.items()}

# ESPN serves some league logos from non-default paths; others have none at all.
_LOGO_OVERRIDE = {
    "epl": "https://a.espncdn.com/i/leaguelogos/soccer/500/23.png",
    "ucl": "https://a.espncdn.com/i/leaguelogos/soccer/500/2.png",
    "mls": "https://a.espncdn.com/i/leaguelogos/soccer/500/19.png",
    "wc":  "https://a.espncdn.com/i/leaguelogos/soccer/500/9.png",
    "cfb": "https://a.espncdn.com/i/espn/misc_logos/500/ncaa.png",
    "cbb": "https://a.espncdn.com/i/espn/misc_logos/500/ncaa.png",
}
_NO_LOGO = {"golf", "atp", "wta"}         # ESPN has no league badge for these


def is_event_league(league) -> bool:
    return league in EVENT


def league_logo(league: str):
    if league in _LOGO_OVERRIDE:
        return _LOGO_OVERRIDE[league]
    if league in _NO_LOGO:
        return None
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
                "id": e.get("id"),
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
    """(wins, losses, draws) from completed games for the followed team."""
    w = l = d = 0
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
            else:
                d += 1
    return w, l, d


def record_str(league: str, w: int, l: int, d: int) -> str:
    return f"{w}-{d}-{l}" if league in SOCCER else f"{w}-{l}"


@st.cache_data(ttl=1800, show_spinner=False)
def game_insight(league: str, event_id):
    """Pre-game context for a matchup from ESPN's event summary: both teams' records,
    the head-to-head season series, and the venue. Returns a small dict or None."""
    if not event_id:
        return None
    try:
        sp, lg = LEAGUES[league][0], LEAGUES[league][1]
        d = requests.get(f"{_BASE}/{sp}/{lg}/summary",
                         params={"event": event_id}, headers=_UA, timeout=20).json()
        out = {}
        comp = ((d.get("header") or {}).get("competitions") or [{}])[0]

        # Win probability (ESPN matchup predictor): {team_id: pct}
        proj = {}
        pr = d.get("predictor") or {}
        for side in ("homeTeam", "awayTeam"):
            o = pr.get(side) or {}
            if o.get("id") and o.get("gameProjection"):
                try:
                    proj[str(o["id"])] = round(float(o["gameProjection"]))
                except Exception:
                    pass

        # Standings: {team_id: {rank, division, gb, streak}}
        standings = {}
        for g in (d.get("standings") or {}).get("groups", []):
            div = re.sub(r"^\d{4}\s+", "", (g.get("header") or "")).replace("Standings", "").strip()
            entries = (g.get("standings") or {}).get("entries", [])
            for idx, e in enumerate(entries):
                stt = {x.get("name"): x.get("displayValue") for x in e.get("stats", [])}
                standings[str(e.get("id"))] = {
                    "rank": idx + 1, "division": div,
                    "gb": stt.get("gamesBehind"), "streak": stt.get("streak")}

        teams = []
        for cz in comp.get("competitors", []):
            t = cz.get("team") or {}
            tid = str(t.get("id"))
            recs = cz.get("record") or []
            overall = None
            for r in recs:
                if (r.get("type") or r.get("name") or "").lower() in ("total", "overall"):
                    overall = r.get("summary")
                    break
            if not overall and recs:
                overall = recs[0].get("summary")
            sd = standings.get(tid, {})
            teams.append({"id": tid, "name": t.get("displayName"), "abbrev": t.get("abbreviation"),
                          "home": cz.get("homeAway") == "home", "record": overall,
                          "logo": (t.get("logos") or [{}])[0].get("href") or t.get("logo"),
                          "win_pct": proj.get(tid), "rank": sd.get("rank"),
                          "division": sd.get("division"), "gb": sd.get("gb"),
                          "streak": sd.get("streak")})
        out["teams"] = teams
        # Head-to-head series — prefer a season-long entry, else the current set
        ss = d.get("seasonseries") or []
        chosen = None
        for s in ss:
            if "season" in (s.get("type") or "").lower():
                chosen = s
                break
        chosen = chosen or (ss[0] if ss else None)
        if chosen:
            out["series"] = chosen.get("summary")
            out["series_title"] = chosen.get("title") or "Series"
        out["venue"] = ((d.get("gameInfo") or {}).get("venue") or {}).get("fullName")
        return out if (teams or out.get("series")) else None
    except Exception:
        return None


# ---------------- Event-model series (F1 / golf / UFC / tennis) ----------------
def encode_series_id(league: str) -> int:
    """Negative watchlist id for following a whole series (team_id slot = 0)."""
    return encode_id(league, 0)


@st.cache_data(ttl=3600, show_spinner=False)
def get_event_schedule(league: str):
    """Season calendar + current/next event for an event-model series.

    Returns {"events": [{label, start, end}], "current": {...} or None}. The
    season calendar comes from leagues[0].calendar (labeled for F1/golf/UFC; just
    daily dates for tennis, which we drop), and the current event from events[0]."""
    try:
        sp, lg = LEAGUES[league][0], LEAGUES[league][1]
        d = requests.get(f"{_BASE}/{sp}/{lg}/scoreboard", headers=_UA, timeout=20).json()
        lg0 = (d.get("leagues") or [{}])[0]
        events = []
        for c in (lg0.get("calendar") or []):
            if isinstance(c, dict) and c.get("label"):
                events.append({
                    "label": c.get("label"),
                    "start": (c.get("startDate") or "")[:10],
                    "end": (c.get("endDate") or "")[:10],
                })
        events.sort(key=lambda e: e["start"] or "")

        cur = None
        ev = d.get("events") or []
        if ev and ev[0]:
            e = ev[0]
            comp = (e.get("competitions") or [{}])[0]
            stype = ((comp.get("status") or {}).get("type")
                     or (e.get("status") or {}).get("type") or {})
            net = ""
            bc = comp.get("broadcasts") or []
            if bc:
                m = bc[0]
                names = m.get("names") or []
                if not names and m.get("media"):
                    sn = (m["media"] or {}).get("shortName")
                    names = [sn] if sn else []
                net = ", ".join(n for n in names if n)
            venue = ((comp.get("venue") or {}).get("fullName")
                     or (e.get("venue") or {}).get("fullName"))
            cur = {
                "name": e.get("name") or e.get("shortName"),
                "date": (e.get("date") or "")[:10],
                "datetime": e.get("date") or "",
                "venue": venue,
                "status": stype.get("description") or stype.get("name"),
                "completed": bool(stype.get("completed")),
                "network": net,
            }
        return {"events": events, "current": cur}
    except Exception:
        return {"events": [], "current": None}
