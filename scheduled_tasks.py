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

            # Send reminders to each user
            emails_sent = 0
            for user_id, shows in users_shows.items():
                try:
                    # Get user email
                    user_result = self.client.table("users").select("email").eq("id", user_id).execute()
                    if not user_result.data:
                        continue

                    user_email = user_result.data[0]["email"]

                    # Send email and create notifications for each show
                    for show in shows:
                        notifications.notify_new_episode(
                            client=self.client,
                            user_id=user_id,
                            show_title=show["title"],
                            show_id=show["tmdb_id"],
                            air_date=show["next_air_date"],
                            send_email=True
                        )
                        emails_sent += 1

                    logger.info(f"Sent {len(shows)} reminders to {user_email}")

                except Exception as e:
                    logger.error(f"Error sending reminders to user {user_id}: {e}")
                    continue

            logger.info(f"Daily reminder job complete: {emails_sent} emails sent")

        except Exception as e:
            logger.error(f"Error in daily reminder job: {e}")

    def _send_weekly_preview_to_all_users(self):
        """Send weekly preview to all users"""
        try:
            logger.info("Starting weekly preview job...")

            # Get date range (today + 7 days)
            today = dt.date.today()
            week_later = today + dt.timedelta(days=7)

            # Get all users
            users_result = self.client.table("users").select("id, email").execute()
            if not users_result.data:
                logger.info("No users found")
                return

            previews_sent = 0

            for user in users_result.data:
                try:
                    user_id = user["id"]
                    user_email = user["email"]

                    # Get shows airing this week for this user
                    shows_result = self.client.table("shows")\
                        .select("title, next_air_date, provider_name")\
                        .eq("user_id", user_id)\
                        .gte("next_air_date", today.isoformat())\
                        .lte("next_air_date", week_later.isoformat())\
                        .order("next_air_date")\
                        .execute()

                    shows = shows_result.data

                    if not shows:
                        logger.info(f"No shows this week for {user_email}")
                        continue

                    # Send weekly preview email
                    self._send_weekly_preview_email(user_email, shows)

                    # Create in-app notification
                    show_list = "\n".join([f"• {s['title']} ({s['next_air_date']})" for s in shows[:5]])
                    if len(shows) > 5:
                        show_list += f"\n• ...and {len(shows) - 5} more"

                    notifications.create_notification(
                        client=self.client,
                        user_id=user_id,
                        notification_type="reminder",
                        title=f"This Week: {len(shows)} Episodes Airing",
                        message=f"You have {len(shows)} new episodes this week:\n{show_list}",
                        send_email=False  # Already sent via preview email
                    )

                    previews_sent += 1
                    logger.info(f"Sent weekly preview to {user_email} ({len(shows)} shows)")

                except Exception as e:
                    logger.error(f"Error sending preview to user {user['id']}: {e}")
                    continue

            logger.info(f"Weekly preview job complete: {previews_sent} previews sent")

        except Exception as e:
            logger.error(f"Error in weekly preview job: {e}")

    def _send_weekly_preview_email(self, user_email: str, shows: list):
        """Send weekly preview email to a user"""
        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail, Email, To, Content

            sg_api_key = os.getenv("SENDGRID_API_KEY")
            if not sg_api_key:
                logger.warning("SendGrid API key not configured")
                return

            # Group shows by day
            shows_by_day = {}
            for show in shows:
                air_date = show["next_air_date"]
                if air_date not in shows_by_day:
                    shows_by_day[air_date] = []
                shows_by_day[air_date].append(show)

            # Build email HTML
            html_content = """
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 28px;">🍿 StreamGenie</h1>
                    <p style="color: white; margin: 10px 0 0 0; font-size: 18px;">Your Weekly Preview</p>
                </div>
                <div style="background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px;">
                    <h2 style="color: #333; margin-top: 0;">This Week's New Episodes</h2>
                    <p style="color: #666; font-size: 16px;">You have {count} new episodes airing this week!</p>
            """.format(count=len(shows))

            # Add shows grouped by day
            for air_date in sorted(shows_by_day.keys()):
                date_obj = dt.date.fromisoformat(air_date)
                day_name = date_obj.strftime("%A, %B %d")

                html_content += f"""
                    <div style="background: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #667eea;">
                        <h3 style="margin: 0 0 10px 0; color: #667eea;">{day_name}</h3>
                """

                for show in shows_by_day[air_date]:
                    html_content += f"""
                        <div style="padding: 10px 0; border-bottom: 1px solid #eee;">
                            <strong style="color: #333; font-size: 16px;">📺 {show['title']}</strong><br>
                            <span style="color: #999; font-size: 14px;">{show['provider_name']}</span>
                        </div>
                    """

                html_content += "</div>"

            html_content += """
                    <p style="color: #999; font-size: 14px; margin-top: 30px; text-align: center;">
                        Sent by StreamGenie - Your personal streaming tracker<br>
                        <a href="https://streamgenie-estero.streamlit.app" style="color: #667eea;">Open StreamGenie</a>
                    </p>
                </div>
            </body>
            </html>
            """

            from_email = Email(os.getenv("SENDGRID_FROM_EMAIL", "joe@outdoorkitchenstore.com"))
            to_email = To(user_email)
            subject = f"🍿 This Week: {len(shows)} New Episodes"
            content = Content("text/html", html_content)

            mail = Mail(from_email, to_email, subject, content)
            mail.reply_to = Email("jjwoods@gmail.com")

            sg = sendgrid.SendGridAPIClient(api_key=sg_api_key)
            sg.send(mail)

            logger.info(f"Weekly preview email sent to {user_email}")

        except Exception as e:
            logger.error(f"Error sending weekly preview email: {e}")

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
