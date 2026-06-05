"""
Weekly newsletter — the ONLY email StreamGenie sends.

One Sunday-evening email per user covering the week ahead:
  • This Week on Your Watchlist (episodes by day, with the app to use)
  • Premieres & Finales (season/series premieres and finales, via TMDB episode_type)
  • Sports This Week (games for followed teams, with broadcast network)
  • Leaving Soon (watchlist titles about to leave a service)
  • Recommended For You (TMDB recommendations seeded from the watchlist)

Everything else (day-of reminders, finales, status changes, leaving alerts) is
in-app-bell only — see notifications.py / show_status.py / cron_runner.py.

Skips users with nothing happening (recommendations alone don't justify an email).
Race-proof: an atomic claim on the notifications table (weekly_digest + week key)
means only one app instance ever sends a given user's newsletter for a given week.
"""
import datetime as dt
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional

import requests

import genie
import mailer
import preferences
import leaving_soon as leaving_mod
import sports

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"


def _tmdb(path: str, **params) -> Dict[str, Any]:
    params.update(api_key=TMDB_API_KEY, language="en-US")
    r = requests.get(f"{TMDB_BASE}{path}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


# ---------------- section builders ----------------

def build_sections(client, user_id: str) -> Dict[str, Any]:
    """Gather all newsletter sections for one user. Each section may be empty."""
    today = dt.date.today()
    week_end = today + dt.timedelta(days=7)
    t_iso, w_iso = today.isoformat(), week_end.isoformat()

    rows = client.table("shows")\
        .select("tmdb_id,title,provider_name,next_air_date")\
        .eq("user_id", user_id).execute().data or []
    tv = [r for r in rows if (r.get("tmdb_id") or 0) > 0]
    sports_rows = [r for r in rows if (r.get("tmdb_id") or 0) < 0]
    wl_ids = {r["tmdb_id"] for r in tv}

    # --- This week on your watchlist ---
    airing = sorted(
        [r for r in tv if r.get("next_air_date") and t_iso <= r["next_air_date"] <= w_iso],
        key=lambda r: r["next_air_date"])

    # --- Premieres & finales (TMDB next_episode_to_air on this week's shows) ---
    highlights = []
    for r in airing[:15]:
        try:
            d = _tmdb(f"/tv/{r['tmdb_id']}")
            ep = d.get("next_episode_to_air") or {}
            if str(ep.get("air_date")) != r["next_air_date"]:
                continue
            season = ep.get("season_number")
            tag = None
            if ep.get("episode_number") == 1:
                tag = "Series premiere" if season == 1 else f"Season {season} premiere"
            etype = (ep.get("episode_type") or "").lower()
            if etype == "finale":
                ended = d.get("status") in ("Ended", "Canceled")
                tag = "Series finale" if ended else f"Season {season} finale"
            elif etype == "mid_season" and not tag:
                tag = "Mid-season finale"
            if tag:
                highlights.append({"title": r["title"], "date": r["next_air_date"],
                                   "tag": tag, "provider": r.get("provider_name") or ""})
        except Exception:
            continue

    # --- Sports this week (followed teams; whole-series follows use the calendar) ---
    games, seen_events = [], set()
    for r in sports_rows:
        league, team_id = sports.decode_id(r["tmdb_id"])
        if not league:
            continue
        try:
            if team_id == "0":  # whole-series follow (F1, golf, UFC, ...)
                cal = sports.get_event_schedule(league) or {}
                for ev in cal.get("events", []):
                    if (ev.get("start") or "") <= w_iso and (ev.get("end") or "") >= t_iso:
                        key = (league, ev.get("label"))
                        if key in seen_events:
                            continue
                        seen_events.add(key)
                        games.append({"date": ev.get("start") or t_iso,
                                      "matchup": ev.get("label") or r["title"],
                                      "network": "", "team": r["title"]})
                continue
            for g in sports.get_team_schedule(league, team_id):
                gd = g.get("date") or ""
                if not (t_iso <= gd <= w_iso) or g.get("completed"):
                    continue
                if g.get("id") in seen_events:
                    continue
                seen_events.add(g.get("id"))
                # Prefer the national broadcast; fall back to plain network, then any cast
                casts = g.get("broadcasts") or []
                nat = next((b["name"] for b in casts if b.get("market") == "national"), "")
                raw = nat or g.get("network") or (casts[0]["name"] if casts else "")
                net = sports.normalize_broadcast(raw) if raw else ""
                games.append({"date": gd, "matchup": f"{g.get('away')} @ {g.get('home')}",
                              "network": net, "team": r["title"]})
        except Exception:
            continue
    games.sort(key=lambda g: g["date"])

    # --- Leaving soon (admin-curated list ∩ this user's watchlist, 14-day window) ---
    leaving = []
    try:
        leaving = [e for e in leaving_mod.get_active(client, within_days=14)
                   if e.get("tmdb_id") in wl_ids]
    except Exception:
        pass

    # --- Recommendation candidates (seeded from up to 4 watchlist shows) ---
    # A pool of ~12 goes to Genie, who curates the 3 best fits for this user's
    # taste; recs defaults to the top 3 by rating when Genie is unavailable.
    pool, seen = [], set(wl_ids)
    for r in tv[:4]:
        try:
            for c in _tmdb(f"/tv/{r['tmdb_id']}/recommendations").get("results", [])[:10]:
                if c.get("id") in seen:
                    continue
                seen.add(c.get("id"))
                pool.append({"title": c.get("name"), "vote": c.get("vote_average") or 0,
                             "votes": c.get("vote_count") or 0, "seed": r["title"]})
        except Exception:
            continue
    candidates = sorted([x for x in pool if x["votes"] >= 50],
                        key=lambda x: -x["vote"])[:12]

    return {"week_start": t_iso, "week_end": w_iso, "airing": airing,
            "highlights": highlights, "games": games, "leaving": leaving,
            "watchlist_titles": [r["title"] for r in tv],
            "rec_candidates": candidates, "recs": candidates[:3]}


def build_chat_context(client, user_id: str) -> Dict[str, Any]:
    """Sections + full watchlist/follows — the grounding context for Ask Genie."""
    s = build_sections(client, user_id)
    rows = client.table("shows")\
        .select("tmdb_id,title,provider_name,next_air_date")\
        .eq("user_id", user_id).execute().data or []
    s["watchlist"] = [
        {"tmdb_id": r["tmdb_id"], "title": r["title"],
         "app": (r.get("provider_name") or None),
         "next_air_date": r.get("next_air_date")}
        for r in rows if (r.get("tmdb_id") or 0) > 0
    ]
    s["sports_follows"] = [
        {"tmdb_id": r["tmdb_id"], "title": r["title"]}
        for r in rows if (r.get("tmdb_id") or 0) < 0
    ]
    return s


# ---------------- rendering ----------------

def _day(date_str: str) -> str:
    try:
        return dt.date.fromisoformat(date_str).strftime("%a %b %-d")
    except Exception:
        return date_str


def _rows(items: List[str]) -> str:
    return "".join(
        f'<p style="margin:6px 0;color:#444;font-size:15px;line-height:1.5;">{x}</p>'
        for x in items)


def _section(title: str, body: str) -> str:
    return f"""
      <div style="background:white;padding:18px 20px;border-radius:8px;margin:14px 0;">
        <h3 style="margin:0 0 10px;color:#333;font-size:17px;">{title}</h3>
        {body}
      </div>"""


def render_html(s: Dict[str, Any], editorial: Optional[Dict[str, Any]] = None) -> str:
    blocks = []
    editorial = editorial or {}
    rec_blurbs = editorial.get("rec_blurbs") or {}

    if editorial.get("intro"):
        blocks.append(f"""
      <div style="background:white;padding:16px 20px;border-radius:8px;margin:14px 0;border-left:4px solid #667eea;">
        <p style="margin:0;color:#444;font-size:15px;line-height:1.6;font-style:italic;">{editorial['intro']}</p>
        <p style="margin:6px 0 0;color:#aaa;font-size:12px;">— Genie, your AI streaming assistant</p>
      </div>""")

    if s["airing"]:
        by_day = defaultdict(list)
        for r in s["airing"]:
            prov = (r.get("provider_name") or "").strip()
            label = f"<b>{r['title']}</b>" + (f" — {prov}" if prov and prov != "Multiple Providers" else "")
            by_day[r["next_air_date"]].append(label)
        body = "".join(
            f'<p style="margin:8px 0 2px;color:#667eea;font-weight:bold;font-size:14px;">{_day(d)}</p>'
            + _rows(by_day[d]) for d in sorted(by_day))
        blocks.append(_section("📺 This Week on Your Watchlist", body))

    if s["highlights"]:
        blocks.append(_section("🎭 Premieres &amp; Finales", _rows([
            f"<b>{h['title']}</b> — {h['tag']} on {_day(h['date'])}"
            + (f" ({h['provider']})" if h.get("provider") else "")
            for h in s["highlights"]])))

    if s["games"]:
        blocks.append(_section("🏈 Sports This Week", _rows([
            f"{_day(g['date'])}: <b>{g['matchup']}</b>"
            + (f" — {g['network']}" if g.get("network") else "")
            for g in s["games"]])))

    if s["leaving"]:
        blocks.append(_section("⏳ Leaving Soon", _rows([
            f"<b>{e.get('title')}</b> leaves {e.get('provider_name')} "
            f"{_day(str(e.get('leaving_date')))} ({e.get('_days_left', '?')} days left)"
            for e in s["leaving"]])))

    if s["recs"]:
        def _rec_line(r):
            line = (f"<b>{r['title']}</b> — rated {r['vote']:.1f}/10 "
                    f"(because you watch {r['seed']})")
            blurb = rec_blurbs.get((r.get("title") or "").strip().lower())
            if blurb:
                line += (f'<br><span style="color:#888;font-size:13px;'
                         f'font-style:italic;">Genie says: {blurb}</span>')
            return line
        blocks.append(_section("✨ Recommended For You", _rows(
            [_rec_line(r) for r in s["recs"]])))

    return f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
      <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 28px;">🍿 StreamGenie</h1>
        <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0; font-size: 15px;">
          Your Week in Streaming · {_day(s['week_start'])} – {_day(s['week_end'])}</p>
      </div>
      <div style="background: #f8f9fa; padding: 20px; border-radius: 0 0 10px 10px;">
        {''.join(blocks)}
        <p style="color: #999; font-size: 13px; margin-top: 24px; text-align: center;">
          Sent weekly by StreamGenie — your personal streaming tracker</p>
      </div>
    </body></html>"""


# ---------------- claim + send ----------------

def _claim(client, user_id: str, week_key: str, summary: str) -> bool:
    """Atomically claim this user's newsletter for the week. True = we send."""
    row = {"user_id": user_id, "notification_type": "weekly_digest",
           "title": "📬 Your Week in Streaming",
           "message": f"Weekly preview for {week_key}: {summary}",
           "related_show_id": 0, "related_show_title": None, "sent_email": True}
    try:
        ins = client.table("notifications").upsert(
            row, on_conflict="user_id,notification_type,related_show_id,message",
            ignore_duplicates=True).execute()
        return bool(ins.data)
    except Exception:
        # unique index not created yet — best-effort check-then-insert
        try:
            dup = client.table("notifications").select("id")\
                .eq("user_id", user_id).eq("notification_type", "weekly_digest")\
                .like("message", f"Weekly preview for {week_key}%").limit(1).execute().data
            if dup:
                return False
            client.table("notifications").insert(row).execute()
            return True
        except Exception:
            return False


def send_weekly_newsletters(client, log=print) -> int:
    """Build + send the weekly newsletter to every user with something happening."""
    if not mailer.is_configured():
        log("newsletter: email transport not configured")
        return 0

    week_key = dt.date.today().isoformat()
    users = client.table("users").select("id,email").execute().data or []
    sent = 0
    for u in users:
        uid, email = u["id"], (u.get("email") or "").strip()
        if not email:
            continue
        try:
            s = build_sections(client, uid)
        except Exception as e:
            log(f"newsletter: build failed for {uid[:8]}: {e}")
            continue

        # Recommendations alone don't justify an email — need real news.
        if not (s["airing"] or s["highlights"] or s["games"] or s["leaving"]):
            log(f"newsletter: nothing happening for {email}, skipping")
            continue

        if not preferences.should_send_email(client, uid, "weekly_preview"):
            log(f"newsletter: email disabled by prefs for {email}")
            continue

        parts = []
        if s["airing"]:
            parts.append(f"{len(s['airing'])} episode{'s' if len(s['airing']) != 1 else ''}")
        if s["games"]:
            parts.append(f"{len(s['games'])} game{'s' if len(s['games']) != 1 else ''}")
        if s["highlights"]:
            parts.append(f"{len(s['highlights'])} premiere/finale")
        if s["leaving"]:
            parts.append(f"{len(s['leaving'])} leaving soon")
        summary = ", ".join(parts)

        if not _claim(client, uid, week_key, summary):
            log(f"newsletter: already sent this week to {email}")
            continue

        # Genie editorial (Claude → Gemini → None); newsletter sends either way
        editorial = genie.generate_editorial(s, log=log)
        if editorial:
            log(f"newsletter: Genie editorial generated for {email}")
            # Genie curates: replace the rating-sorted top 3 with Genie's picks
            # (matched back to the candidate pool so vote/seed metadata is kept)
            by_title = {(c.get("title") or "").strip().lower(): c
                        for c in s.get("rec_candidates", [])}
            picked = [by_title[t] for t in editorial.get("picks", []) if t in by_title]
            if picked:
                s["recs"] = picked[:3]

        subject = f"StreamGenie Weekly: {summary}"
        if mailer.send_email(email, subject, render_html(s, editorial)):
            sent += 1
            log(f"newsletter: sent to {email} ({summary})")
        else:
            log(f"newsletter: send FAILED for {email}")
    return sent
