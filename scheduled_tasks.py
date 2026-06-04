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

            logger.info(f"Daily reminder job complete: {emails_sent} emails sent")

        except Exception as e:
            logger.error(f"Error in daily reminder job: {e}")

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

        # Schedule default jobs
        _scheduler.schedule_daily_reminders(hour=8, minute=0, timezone="America/New_York")
        _scheduler.schedule_weekly_preview(day_of_week='sun', hour=18, minute=0, timezone="America/New_York")

    return _scheduler


def get_scheduler() -> Optional[TaskScheduler]:
    """Get the global scheduler instance"""
    return _scheduler
