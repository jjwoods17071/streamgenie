"""
Scheduled background tasks for StreamGenie
Handles scheduled email reminders and background jobs
"""
import os
import datetime as dt
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from supabase import Client
import notifications
from typing import Optional
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    Manages scheduled background tasks
    """

    def __init__(self, client: Client):
        self.client = client
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        logger.info("Task scheduler started")

    def schedule_daily_reminders(self, hour: int = 8, minute: int = 0, timezone: str = "America/New_York"):
        """
        Schedule daily email reminders at a specific time

        Args:
            hour: Hour of day (0-23)
            minute: Minute of hour (0-59)
            timezone: Timezone string (e.g., 'America/New_York', 'UTC')
        """
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            timezone=timezone
        )

        self.scheduler.add_job(
            func=self._send_daily_reminders_to_all_users,
            trigger=trigger,
            id='daily_reminders',
            replace_existing=True,
            name='Send daily email reminders'
        )

        logger.info(f"Scheduled daily reminders for {hour:02d}:{minute:02d} {timezone}")

    def schedule_weekly_preview(self, day_of_week: str = 'sun', hour: int = 18, minute: int = 0, timezone: str = "America/New_York"):
        """
        Schedule weekly preview emails

        Args:
            day_of_week: Day of week (mon, tue, wed, thu, fri, sat, sun)
            hour: Hour of day (0-23)
            minute: Minute of hour (0-59)
            timezone: Timezone string
        """
        trigger = CronTrigger(
            day_of_week=day_of_week,
            hour=hour,
            minute=minute,
            timezone=timezone
        )

        self.scheduler.add_job(
            func=self._send_weekly_preview_to_all_users,
            trigger=trigger,
            id='weekly_preview',
            replace_existing=True,
            name='Send weekly preview emails'
        )

        logger.info(f"Scheduled weekly preview for {day_of_week} {hour:02d}:{minute:02d} {timezone}")

    def _send_daily_reminders_to_all_users(self):
        """Send daily reminders to all users with shows airing today"""
        try:
            logger.info("Starting daily reminder job...")

            # Yesterday's "airing today" notices are stale — those episodes now
            # show in Catch Up. Clear them before posting today's digest.
            expired = notifications.expire_stale_airing(self.client)
            if expired:
                logger.info(f"Expired {expired} stale airing notification(s)")

            today = dt.date.today().isoformat()

            # Get all users who have shows airing today
            result = self.client.table("shows")\
                .select("user_id, tmdb_id, title, provider_name, next_air_date")\
                .eq("next_air_date", today)\
                .execute()

            if not result.data:
                logger.info("No shows airing today")
                return

            # Group shows by user
            users_shows = {}
            for show in result.data:
                user_id = show["user_id"]
                if user_id not in users_shows:
                    users_shows[user_id] = []
                users_shows[user_id].append(show)

            logger.info(f"Found {len(users_shows)} users with shows airing today")

            # Send ONE consolidated reminder per user (not one per show).
            # Days with nothing airing were already skipped above — no empty digests.
            emails_sent = 0
            for user_id, shows in users_shows.items():
                try:
                    # Get user email
                    user_result = self.client.table("users").select("email").eq("id", user_id).execute()
                    if not user_result.data:
                        continue

                    user_email = user_result.data[0]["email"]

                    notifications.notify_airing_digest(
                        client=self.client,
                        user_id=user_id,
                        shows=shows
                    )
                    emails_sent += 1

                    logger.info(f"Sent digest ({len(shows)} shows) to {user_email}")

                except Exception as e:
                    logger.error(f"Error sending reminders to user {user_id}: {e}")
                    continue

            logger.info(f"Daily reminder job complete: {emails_sent} digest(s) sent")

            # Catch-up nudges (bell only, spoiler-free, ≤3 shows/user, weekly per show)
            try:
                self._send_catchup_nudges()
            except Exception as e:
                logger.error(f"Error in catch-up nudges: {e}")

        except Exception as e:
            logger.error(f"Error in daily reminder job: {e}")

    def _aired_profile(self, tmdb_id: int):
        """(aired_episode_count, last_ep_is_finale, series_over) from TMDB."""
        import os as _os
        import requests as _rq
        key = _os.getenv("TMDB_API_KEY", "").strip()
        d = _rq.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}",
                    params={"api_key": key, "language": "en-US"}, timeout=15).json()
        last = d.get("last_episode_to_air") or {}
        ls, le = last.get("season_number"), last.get("episode_number")
        if not ls:
            return 0, False, False
        total = 0
        for season in d.get("seasons", []):
            sn = season.get("season_number") or 0
            if sn == 0:
                continue            # skip specials
            if sn < ls:
                total += season.get("episode_count") or 0
            elif sn == ls:
                total += le or 0
        finale = (last.get("episode_type") or "") == "finale"
        over = d.get("status") in ("Ended", "Canceled")
        return total, finale, over

    def _send_catchup_nudges(self):
        """Spoiler-free bell nudges for shows the user has STARTED and fallen behind on.
        Counts only — never plot. Max 3 shows per user per run; each show nudged at
        most once every 7 days (checked against the notification history)."""
        from collections import Counter
        cutoff = (dt.datetime.utcnow() - dt.timedelta(days=7)).isoformat()
        users = self.client.table("users").select("id").execute().data or []
        sent = 0
        for u in users:
            uid = u["id"]
            wrows = self.client.table("watched_episodes").select("tmdb_id")\
                .eq("user_id", uid).execute().data or []
            if not wrows:
                continue
            wcounts = Counter(x["tmdb_id"] for x in wrows)
            srows = self.client.table("shows").select("tmdb_id,title")\
                .eq("user_id", uid).execute().data or []
            titles = {r["tmdb_id"]: r["title"] for r in srows}
            candidates = []
            for tid, w in wcounts.items():
                if tid not in titles or tid <= 0:
                    continue                      # removed shows / sports
                try:
                    aired, finale, over = self._aired_profile(tid)
                except Exception:
                    continue
                behind = aired - w
                if behind > 0:
                    candidates.append((behind, tid, titles[tid], finale, over))
            for behind, tid, title, finale, over in sorted(candidates, reverse=True)[:3]:
                # weekly cadence per show
                prev = self.client.table("notifications").select("created_at")\
                    .eq("user_id", uid).eq("notification_type", "catchup_nudge")\
                    .eq("related_show_id", tid).gte("created_at", cutoff)\
                    .limit(1).execute().data
                if prev:
                    continue
                tail = "."
                if finale and over:
                    tail = " — the series finale is in there."
                elif finale:
                    tail = " — including a season finale."
                notifications.create_notification(
                    client=self.client, user_id=uid,
                    notification_type="catchup_nudge",
                    title=f"📥 Catch up: {title}",
                    message=f"You have {behind} aired episode{'s' if behind != 1 else ''} "
                            f"waiting{tail} See the Catch Up tab.",
                    related_show_id=tid, related_show_title=title,
                    send_email=False)
                sent += 1
        logger.info(f"Catch-up nudges: {sent} sent")

    def _send_weekly_preview_to_all_users(self):
        """Send the weekly newsletter (the only email StreamGenie sends).

        Delegates to newsletter.send_weekly_newsletters: one Sunday email per
        user covering the week ahead (episodes, premieres/finales, sports,
        leaving-soon, recommendations). Skips users with nothing happening and
        is race-proof via an atomic weekly_digest claim in the notifications
        table, so concurrent app instances can't double-send.
        """
        try:
            import newsletter
            sent = newsletter.send_weekly_newsletters(
                self.client, log=lambda m: logger.info(m))
            logger.info(f"Weekly newsletter job complete: {sent} sent")
        except Exception as e:
            logger.error(f"Error in weekly newsletter job: {e}")

    def test_daily_reminders_now(self):
        """Manually trigger daily reminders (for testing)"""
        logger.info("Manually triggering daily reminders...")
        self._send_daily_reminders_to_all_users()

    def test_weekly_preview_now(self):
        """Manually trigger weekly preview (for testing)"""
        logger.info("Manually triggering weekly preview...")
        self._send_weekly_preview_to_all_users()

    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Task scheduler stopped")

    def get_jobs(self):
        """Get list of scheduled jobs"""
        return self.scheduler.get_jobs()


# Global scheduler instance
_scheduler: Optional[TaskScheduler] = None


def init_scheduler(client: Client) -> TaskScheduler:
    """
    Initialize the global task scheduler

    Args:
        client: Supabase client

    Returns:
        TaskScheduler instance
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler(client)

        # NOTE: the recurring reminder/newsletter jobs are intentionally NOT scheduled
        # here. They run from GitHub Actions cron (cron_runner.py) instead — a single
        # fresh runner per fire. The in-app APScheduler lived inside long-running
        # Streamlit Cloud containers: several would be awake at once AND could be running
        # stale code (pre-deploy), so each fired the 8 AM job independently and produced
        # duplicate notifications that slipped past the dedup index. GitHub Actions is
        # the authoritative scheduler; this object stays only for the manual
        # test_*_now() buttons in the admin panel.
        if os.getenv("ENABLE_INAPP_SCHEDULER", "").strip() == "1":
            _scheduler.schedule_daily_reminders(hour=8, minute=0, timezone="America/New_York")
            _scheduler.schedule_weekly_preview(day_of_week='sun', hour=18, minute=0, timezone="America/New_York")

    return _scheduler


def get_scheduler() -> Optional[TaskScheduler]:
    """Get the global scheduler instance"""
    return _scheduler
