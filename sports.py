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

# Local O&O / major-market affiliate call signs → their national network, so a game on
# (e.g.) WMAQ shows as "NBC" the way a cable guide would — we don't reinvent station data,
# we normalize the common big-market affiliates that actually carry games.
_AFFILIATE_NETWORK = {
    # NBC
    "WNBC": "NBC", "KNBC": "NBC", "WMAQ": "NBC", "WCAU": "NBC", "KNTV": "NBC", "WRC": "NBC",
    "KXAS": "NBC", "WTVJ": "NBC", "KNSD": "NBC", "WBTS": "NBC", "WVIT": "NBC", "KPNX": "NBC",
    "WHDH": "NBC", "KING": "NBC",
    # ABC
    "WABC": "ABC", "KABC": "ABC", "WLS": "ABC", "WPVI": "ABC", "KGO": "ABC", "KTRK": "ABC",
    "WTVD": "ABC", "KFSN": "ABC", "WSB": "ABC", "KMGH": "ABC", "WFAA": "ABC", "KOMO": "ABC",
    "WXYZ": "ABC", "KSTP": "ABC",
    # CBS
    "WCBS": "CBS", "KCBS": "CBS", "WBBM": "CBS", "KYW": "CBS", "KPIX": "CBS", "KTVT": "CBS",
    "KDKA": "CBS", "WBZ": "CBS", "WFOR": "CBS", "KCNC": "CBS", "WCCO": "CBS", "WJZ": "CBS",
    "KCAL": "CBS", "WWJ": "CBS", "KIRO": "CBS",
    # FOX
    "WNYW": "FOX", "KTTV": "FOX", "WFLD": "FOX", "WTXF": "FOX", "KTVU": "FOX", "KRIV": "FOX",
    "KDFW": "FOX", "WTTG": "FOX", "WJBK": "FOX", "KSAZ": "FOX", "WTVT": "FOX", "KMSP": "FOX",
    "WAGA": "FOX", "KCPQ": "FOX",
}


def normalize_broadcast(name):
    """Map a local affiliate call sign (e.g. 'WMAQ', 'WMAQ-TV', 'WMAQ 5') to its national
    network ('NBC'); pass everything else (national nets, RSNs, streamers) through unchanged."""
    if not name:
        return name
    token = re.split(r"[\s\-]", name.strip())[0].upper()
    return _AFFILIATE_NETWORK.get(token, name.strip())

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
    "wwc":  ("soccer", "fifa.wwc",         "🌍 Women's World Cup", 17, None),
    "cfb":  ("football",   "college-football",         "🏈 College FB", 10, None),
    "cbb":  ("basketball", "mens-college-basketball",  "🏀 College BB", 11, None),
    # Event-model series: you follow the whole series, "episodes" are races/tournaments/cards.
    "f1":   ("racing", "f1",   "🏎️ F1",        12, None),
    "golf": ("golf",   "pga",  "⛳ PGA Tour",   13, None),
    "ufc":  ("mma",    "ufc",  "🥊 UFC",        14, None),
    "atp":  ("tennis", "atp",  "🎾 ATP",        15, None),
    "wta":  ("tennis", "wta",  "🎾 WTA",        16, None),
}
SOCCER = {"epl", "ucl", "mls", "wc", "wwc"}      # leagues that can draw → W-D-L records
EVENT = {"f1", "golf", "ufc", "atp", "wta"}   # series, not head-to-head teams
SEASON_CAL = {"f1", "golf", "ufc"}        # event leagues with a labeled season calendar
_IDX_TO_LEAGUE = {v[3]: k for k, v in LEAGUES.items()}

# ESPN serves some league logos from non-default paths; others have none at all.
_LOGO_OVERRIDE = {
    "epl": "https://a.espncdn.com/i/leaguelogos/soccer/500/23.png",
    "ucl": "https://a.espncdn.com/i/leaguelogos/soccer/500/2.png",
    "mls": "https://a.espncdn.com/i/leaguelogos/soccer/500/19.png",
    "wc":  "https://a.espncdn.com/i/leaguelogos/soccer/500/4.png",
    "wwc": "https://a.espncdn.com/i/leaguelogos/soccer/500/60.png",
    "cfb": "https://a.espncdn.com/i/espn/misc_logos/500/ncaa.png",
    "cbb": "https://a.espncdn.com/i/espn/misc_logos/500/ncaa.png",
    "golf": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/pgatour.png",
    # ESPN has no ATP/WTA brand badge — its tennis icon is the best available (the
    # 🎾 ATP / 🎾 WTA text label distinguishes the two).
    "atp": "https://a.espncdn.com/combiner/i?img=/redesign/assets/img/icons/ESPN-icon-tennis.png",
    "wta": "https://a.espncdn.com/combiner/i?img=/redesign/assets/img/icons/ESPN-icon-tennis.png",
}
_NO_LOGO = set()                            # all leagues now resolve a logo


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


@st.cache_data(ttl=1800, show_spinner=False)
def _league_fixtures(league: str):
    """All scheduled games for a league via a single date-ranged scoreboard query
    (today .. +75d). ESPN leaves the per-team /schedule endpoint EMPTY for
    tournaments like the World Cup, but the ranged scoreboard returns the full
    fixture list. One request — no preliminary calendar call (that made ESPN's edge
    intermittently return an empty set)."""
    try:
        sp, lg = LEAGUES[league][0], LEAGUES[league][1]
        s = dt.date.today()
        e = s + dt.timedelta(days=75)
        rng = f"{s.strftime('%Y%m%d')}-{e.strftime('%Y%m%d')}"
        d = requests.get(f"{_BASE}/{sp}/{lg}/scoreboard",
                         params={"dates": rng, "limit": 500}, headers=_UA, timeout=25).json()
        games = []
        for ev in d.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            cs = comp.get("competitors", [])
            home = next((c for c in cs if c.get("homeAway") == "home"), {})
            away = next((c for c in cs if c.get("homeAway") == "away"), {})
            stype = (comp.get("status") or {}).get("type") or {}
            casts = []
            for b in (comp.get("broadcasts") or []):
                if isinstance(b, str):
                    nm, mkt = b, ""
                else:
                    nm = (", ".join(b.get("names", [])) if b.get("names")
                          else (b.get("media") or {}).get("shortName") or b.get("station"))
                    # `market` is a dict {type:...} on most leagues but a plain string
                    # ("national") on the World Cup — handle both.
                    _mk = b.get("market")
                    mkt = (_mk.get("type") if isinstance(_mk, dict) else _mk) or ""
                    mkt = str(mkt).lower()
                if nm:
                    casts.append({"name": nm, "market": mkt})
            net = casts[0]["name"] if casts else ""
            games.append({
                "id": ev.get("id"), "date": (ev.get("date") or "")[:10],
                "datetime": ev.get("date") or "",
                "home": (home.get("team") or {}).get("displayName"),
                "away": (away.get("team") or {}).get("displayName"),
                "home_logo": _logo(home), "away_logo": _logo(away),
                "home_score": _score(home), "away_score": _score(away),
                "status": stype.get("description") or stype.get("name"),
                "completed": bool(stype.get("completed")),
                "network": net, "broadcasts": casts,
            })
        games.sort(key=lambda g: g["datetime"] or "")
        return games
    except Exception:
        return []


@st.cache_data(ttl=900, show_spinner=False)
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
            # Each broadcast tagged National / Home / Away (regional RSN) by ESPN
            casts = []
            for b in bc:
                nm = (", ".join(b.get("names", [])) if b.get("names")
                      else (b.get("media") or {}).get("shortName") or b.get("station"))
                mkt = ((b.get("market") or {}).get("type") or "").lower()  # national/home/away
                if nm:
                    casts.append({"name": nm, "market": mkt})
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
                "broadcasts": casts,
                "week": wk.get("number") or wk.get("text"),
            })
        games.sort(key=lambda g: g["datetime"] or "")
        if games:
            return games
    except Exception:
        pass
    # Fallback for tournaments (World Cup) with empty per-team schedules: pull the
    # whole league fixture list and keep the games this team plays in.
    try:
        nm = None
        for t in get_teams(league):
            if str(t.get("id")) == str(team_id):
                nm = t.get("name")
                break
        if nm:
            return [g for g in _league_fixtures(league)
                    if g.get("home") == nm or g.get("away") == nm]
    except Exception:
        pass
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

        # Key player per team (headshot): MLB → probable pitcher; else top stat leader
        kplayers = {}
        for grp in (d.get("leaders") or []):
            tid2 = str((grp.get("team") or {}).get("id"))
            cats = grp.get("leaders") or []
            if cats:
                ld = (cats[0].get("leaders") or [{}])[0]
                a = ld.get("athlete") or {}
                cat = cats[0].get("shortDisplayName") or cats[0].get("displayName") or ""
                kplayers[tid2] = {"name": a.get("displayName") or a.get("fullName"),
                                  "headshot": (a.get("headshot") or {}).get("href"),
                                  "note": (f"{ld.get('displayValue','')} {cat}").strip()}

        # Last-5 form: {team_id: ['W','L',...]}
        last5 = {}
        for blk in (d.get("lastFiveGames") or []):
            tid2 = str((blk.get("team") or {}).get("id"))
            res = [e.get("gameResult") for e in (blk.get("events") or []) if e.get("gameResult")]
            if res:
                last5[tid2] = res

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
            # Probable starting pitcher (MLB) / featured player
            pitcher = None
            player = None   # key player + headshot for the player-hero tile
            pr = cz.get("probables") or []
            if pr and isinstance(pr[0], dict):
                ath = pr[0].get("athlete") or {}
                pitcher = ath.get("fullName") or ath.get("displayName")
                if pitcher:
                    player = {"name": pitcher, "headshot": (ath.get("headshot") or {}).get("href"),
                              "note": "Starting pitcher"}
            if not player:
                player = kplayers.get(tid)
            res5 = last5.get(tid) or []
            form = None
            if res5:
                w5, l5 = res5.count("W"), res5.count("L")
                form = {"record": f"{w5}-{l5}", "seq": "".join(r[:1] for r in res5)}
            _col = (t.get("color") or "").lstrip("#")
            _alt = (t.get("alternateColor") or "").lstrip("#")
            teams.append({"id": tid, "name": t.get("displayName"), "abbrev": t.get("abbreviation"),
                          "home": cz.get("homeAway") == "home", "record": overall,
                          "logo": (t.get("logos") or [{}])[0].get("href") or t.get("logo"),
                          "color": f"#{_col}" if _col else None,
                          "alt_color": f"#{_alt}" if _alt else None,
                          "win_pct": proj.get(tid), "rank": sd.get("rank"),
                          "division": sd.get("division"), "gb": sd.get("gb"),
                          "streak": sd.get("streak"), "pitcher": pitcher, "form": form,
                          "player": player})
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

        # Matchup/series title (the 'S5E1' analog): a playoff series state if present,
        # else the season-series record summary. comp["series"] may be a dict or a list.
        _pser = comp.get("series")
        if isinstance(_pser, list):
            _pser = _pser[0] if _pser else {}
        _pser = _pser or {}
        out["matchup_title"] = (_pser.get("summary") or _pser.get("title")
                                or out.get("series"))

        # Broadcast network (ESPN / TNT / ABC / Apple TV+ …) — mirror the streaming logo slot
        network = None
        for b in (comp.get("broadcasts") or d.get("broadcasts") or []):
            if isinstance(b, dict):
                network = ((b.get("media") or {}).get("shortName")
                           or (b.get("names") or [None])[0]
                           or b.get("shortName") or b.get("name"))
            elif isinstance(b, str):
                network = b
            if network:
                break
        out["broadcast"] = normalize_broadcast(network)

        # Venue + weather (weather is generally only present for outdoor games)
        gi = d.get("gameInfo") or {}
        ven = gi.get("venue") or {}
        out["venue"] = ven.get("fullName")
        _addr = ven.get("address") or {}
        out["venue_city"] = ", ".join(x for x in (_addr.get("city"), _addr.get("state")) if x) or None
        wx = gi.get("weather") or {}
        if wx:
            out["weather"] = {"temp": wx.get("temperature") or wx.get("highTemperature"),
                              "summary": (wx.get("displayValue") or "").strip()}
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
        ev = d.get("events") or []
        if not events and ev:
            # Tennis-style: no labeled season calendar — build the schedule from the
            # tournaments listed in events[] (Roland Garros, Boss Open, ...). Dedup by
            # name so multiple draws of one tournament collapse to a single entry.
            _seen = set()
            for _e in ev:
                _nm = _e.get("name") or _e.get("shortName")
                if not _nm or _nm in _seen:
                    continue
                _seen.add(_nm)
                _d = (_e.get("date") or "")[:10]
                events.append({"label": _nm, "start": _d, "end": _d})
        events.sort(key=lambda e: e["start"] or "")

        cur = None
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
