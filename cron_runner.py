#!/usr/bin/env python3
"""
StreamGenie scheduled-jobs runner — invoked by GitHub Actions cron, NOT the in-app
APScheduler (which only runs while the Streamlit app is awake on Streamlit Cloud).

Jobs:
  daily    — email/notify shows airing today          (reuses scheduled_tasks)
  leaving  — alert users when a watchlist title is <= N days from leaving a provider
  status   — refresh TMDB status; notify on Ended/Canceled (reuses show_status)
  weekly   — weekly preview email (runs only on Sundays when job=all)

Env required: SUPABASE_URL, SUPABASE_KEY (service_role/secret), TMDB_API_KEY,
              SENDGRID_API_KEY, SENDGRID_FROM_EMAIL
Usage: python cron_runner.py [--job all|daily|leaving|status|weekly]
                             [--leaving-window 7] [--dry-run]
"""
import os
import sys
import argparse
import datetime as dt

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
import notifications
import scheduled_tasks
import show_status
import leaving_soon


def log(m: str) -> None:
    print(f"[{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] {m}", flush=True)


def get_client():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()
    if not url or not key:
        log("FATAL: SUPABASE_URL / SUPABASE_KEY not set")
        sys.exit(1)
    return create_client(url, key)


def _bare_scheduler(client):
    """A TaskScheduler with its client set but WITHOUT starting APScheduler
    (we only want the job-body methods, not a background thread)."""
    ts = scheduled_tasks.TaskScheduler.__new__(scheduled_tasks.TaskScheduler)
    ts.client = client
    return ts


# ---------------- jobs ----------------
def run_daily(client, dry: bool):
    log("JOB daily: shows airing today")
    if dry:
        today = dt.date.today().isoformat()
        rows = client.table("shows").select("user_id,title,next_air_date")\
            .eq("next_air_date", today).execute().data or []
        log(f"  [dry-run] would notify on {len(rows)} show(s) airing today: "
            f"{[r['title'] for r in rows][:8]}")
        return
    _bare_scheduler(client)._send_daily_reminders_to_all_users()


def run_weekly(client, dry: bool):
    log("JOB weekly: this week's preview")
    if dry:
        today = dt.date.today()
        wk = today + dt.timedelta(days=7)
        rows = client.table("shows").select("user_id,title,next_air_date")\
            .gte("next_air_date", today.isoformat())\
            .lte("next_air_date", wk.isoformat()).execute().data or []
        log(f"  [dry-run] would send weekly preview covering {len(rows)} upcoming episode(s)")
        return
    _bare_scheduler(client)._send_weekly_preview_to_all_users()


def run_leaving(client, window_days: int, dry: bool):
    log(f"JOB leaving: titles leaving within {window_days} days")
    active = leaving_soon.get_active(client, within_days=window_days)
    if not active:
        log("  none in window")
        return
    sent = 0
    for e in active:
        tmdb_id = e["tmdb_id"]
        lv = str(e["leaving_date"])
        prov = e["provider_name"]
        days = e.get("_days_left", 0)
        # users who track this show
        rows = client.table("shows").select("user_id").eq("tmdb_id", tmdb_id).execute().data or []
        users = {r["user_id"] for r in rows}
        if not users:
            log(f"  {e['title']} ({days}d): on nobody's watchlist, skipping")
            continue
        for uid in users:
            # de-dup: one alert per (user, show, leaving_date)
            existing = client.table("notifications").select("message")\
                .eq("user_id", uid).eq("related_show_id", tmdb_id)\
                .eq("notification_type", "leaving_soon").execute().data or []
            if any(lv in (n.get("message") or "") for n in existing):
                continue
            day_word = "day" if days == 1 else "days"
            if dry:
                log(f"  [dry-run] would alert user {uid[:8]} — {e['title']} leaves {prov} {lv} ({days}d)")
                sent += 1
                continue
            notifications.create_notification(
                client=client, user_id=uid, notification_type="leaving_soon",
                title=f"⏳ Leaving {prov} soon: {e['title']}",
                message=f"{e['title']} leaves {prov} on {lv} ({days} {day_word} left). "
                        f"Catch it before it's gone!",
                related_show_id=tmdb_id, related_show_title=e["title"],
                send_email=False)  # bell only; weekly newsletter covers leaving-soon
            sent += 1
            log(f"  alert -> user {uid[:8]} for {e['title']} ({days}d)")
    log(f"  leaving-soon: {sent} alert(s) {'(dry)' if dry else 'sent'}")


def run_status(client, dry: bool):
    log("JOB status: TMDB status sweep (notifies on Ended/Canceled)")
    users = client.table("users").select("id").execute().data or []
    if dry:
        n = client.table("shows").select("tmdb_id").execute().data or []
        log(f"  [dry-run] would sweep {len(n)} show rows across {len(users)} users "
            "(notifications only fire on a status change to Ended/Canceled)")
        return
    changed = 0
    for u in users:
        stats = show_status.check_all_shows_status(client, u["id"])
        changed += stats.get("updated", 0)
    log(f"  status: {changed} status change(s) across {len(users)} users")


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="all",
                    choices=["all", "daily", "leaving", "status", "weekly"])
    ap.add_argument("--leaving-window", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    client = get_client()
    job = args.job
    dry = args.dry_run
    log(f"=== StreamGenie cron_runner job={job} dry_run={dry} ===")

    if job in ("all", "daily"):
        run_daily(client, dry)
    if job in ("all", "leaving"):
        run_leaving(client, args.leaving_window, dry)
    if job in ("all", "status"):
        run_status(client, dry)
    # weekly preview: explicit --job weekly, or Sundays under --job all
    if job == "weekly" or (job == "all" and dt.date.today().weekday() == 6):
        run_weekly(client, dry)

    log("=== done ===")


if __name__ == "__main__":
    main()
