"""
Calendar export for StreamGenie — turn upcoming episodes into calendar events.

- build_ics(events): a VCALENDAR string (one VEVENT per episode) for download and
  import into Apple Calendar / Outlook / Google. Each event carries two VALARM
  reminders (1 day + 1 hour before).
- google_link(event): a Google Calendar "add event" URL (works on desktop + phone,
  no file needed).

An `event` is a dict: {tmdb_id, title, date('YYYY-MM-DD'), season, episode, ep_name}.
Events are timed at 20:00 local (floating time) on the air date — a sensible primetime
default since TMDB only gives a date, and it makes the relative reminders intuitive.
"""
import datetime as dt
from urllib.parse import quote


def _esc(s: str) -> str:
    """Escape text for an ICS field."""
    s = s or ""
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _se(ev: dict) -> str:
    if ev.get("season") and ev.get("episode"):
        return f"S{ev['season']}E{ev['episode']}"
    return ""


def _summary(ev: dict) -> str:
    se = _se(ev)
    out = ev.get("title") or "Episode"
    if se:
        out += f" — {se}"
    if ev.get("ep_name"):
        out += f": {ev['ep_name']}"
    return out


def _vevent(ev: dict, stamp: str) -> str:
    d = dt.date.fromisoformat(ev["date"])
    start = d.strftime("%Y%m%dT200000")   # 8:00pm, floating local time
    end = d.strftime("%Y%m%dT210000")
    uid = f"sg-{ev.get('tmdb_id', 'x')}-{_se(ev) or d.isoformat()}@streamgenie"
    return "\r\n".join([
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{start}",
        f"DTEND:{end}",
        f"SUMMARY:{_esc(_summary(ev))}",
        f"DESCRIPTION:{_esc('New episode — tracked in StreamGenie')}",
        "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Episode tomorrow", "TRIGGER:-P1D", "END:VALARM",
        "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Episode in 1 hour", "TRIGGER:-PT1H", "END:VALARM",
        "END:VEVENT",
    ])


def build_ics(events) -> str:
    """A full VCALENDAR for one or many events."""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0",
           "PRODID:-//StreamGenie//Episode Schedule//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for ev in events:
        try:
            out.append(_vevent(ev, stamp))
        except Exception:
            continue
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def google_link(ev: dict) -> str:
    """A Google Calendar add-event URL for a single episode (with a 1-day reminder hint
    in the details — Google can't set the alarm via URL, so we note it)."""
    d = dt.date.fromisoformat(ev["date"])
    dates = f"{d.strftime('%Y%m%dT200000')}/{d.strftime('%Y%m%dT210000')}"
    details = "Tracked in StreamGenie. Tip: set a reminder the day before."
    return ("https://calendar.google.com/calendar/render?action=TEMPLATE"
            f"&text={quote(_summary(ev))}"
            f"&dates={dates}"
            f"&details={quote(details)}")
