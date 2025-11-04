"""
Show Status Tracking Module
Checks TMDB for show status (Returning Series, Ended, Canceled, etc.)
and sends notifications when status changes
"""
import os
import requests
import datetime as dt
from supabase import Client
from typing import Optional, Dict, List
import logging
import notifications

logger = logging.getLogger(__name__)

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"


def fetch_show_status(tmdb_id: int) -> Optional[Dict]:
    """
    Fetch show details from TMDB including status

    Args:
        tmdb_id: TMDB show ID

    Returns:
        Dictionary with status, name, last_air_date, etc. or None if error
    """
    try:
        url = f"{TMDB_BASE}/tv/{tmdb_id}"
        params = {
            "api_key": TMDB_API_KEY,
            "append_to_response": "content_ratings"
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        return {
            "tmdb_id": tmdb_id,
            "name": data.get("name", "Unknown"),
            "status": data.get("status", "Unknown"),  # "Returning Series", "Ended", "Canceled", "In Production"
            "type": data.get("type", "Scripted"),  # "Scripted", "Documentary", "Reality", etc.
            "last_air_date": data.get("last_air_date"),
            "number_of_seasons": data.get("number_of_seasons", 0),
            "number_of_episodes": data.get("number_of_episodes", 0),
            "in_production": data.get("in_production", False),
            "next_episode_to_air": data.get("next_episode_to_air"),
            "last_episode_to_air": data.get("last_episode_to_air")
        }
    except Exception as e:
        logger.error(f"Error fetching status for TMDB ID {tmdb_id}: {e}")
        return None


def update_show_status(client: Client, user_id: str, tmdb_id: int, show_title: str) -> Optional[str]:
    """
    Update show status in database and send notifications if changed

    Args:
        client: Supabase client
        user_id: User ID
        tmdb_id: TMDB show ID
        show_title: Show title

    Returns:
        New status string or None if error
    """
    try:
        # Fetch current status from TMDB
        status_info = fetch_show_status(tmdb_id)
        if not status_info:
            return None

        new_status = status_info["status"]

        # Get current status from database
        result = client.table("shows")\
            .select("show_status, last_status_check")\
            .eq("user_id", user_id)\
            .eq("tmdb_id", tmdb_id)\
            .execute()

        if not result.data or len(result.data) == 0:
            # Show not found in user's watchlist
            return None

        old_status = result.data[0].get("show_status", "Unknown")
        status_changed = old_status != new_status

        # Update status in database
        client.table("shows")\
            .update({
                "show_status": new_status,
                "last_status_check": dt.datetime.now().isoformat()
            })\
            .eq("user_id", user_id)\
            .eq("tmdb_id", tmdb_id)\
            .execute()

        logger.info(f"Updated status for {show_title} (ID: {tmdb_id}): {old_status} -> {new_status}")

        # Send notifications if status changed to Ended or Canceled
        if status_changed and new_status in ["Ended", "Canceled"]:
            notify_status_change(client, user_id, tmdb_id, show_title, old_status, new_status, status_info)

        return new_status
    except Exception as e:
        logger.error(f"Error updating show status: {e}")
        return None


def notify_status_change(
    client: Client,
    user_id: str,
    tmdb_id: int,
    show_title: str,
    old_status: str,
    new_status: str,
    status_info: Dict
):
    """
    Send notification when show status changes to Ended or Canceled

    Args:
        client: Supabase client
        user_id: User ID
        tmdb_id: TMDB show ID
        show_title: Show title
        old_status: Previous status
        new_status: New status
        status_info: Full status info from TMDB
    """
    try:
        if new_status == "Ended":
            # Series finale notification
            last_episode = status_info.get("last_episode_to_air", {})
            last_air_date = status_info.get("last_air_date", "Unknown")

            title = f"🎭 Series Finale: {show_title}"
            message = f"{show_title} has ended. The final episode aired on {last_air_date}."

            if last_episode:
                season = last_episode.get("season_number")
                episode = last_episode.get("episode_number")
                if season and episode:
                    message += f" (S{season}E{episode})"

            notifications.create_notification(
                client=client,
                user_id=user_id,
                notification_type="series_finale",
                title=title,
                message=message,
                related_show_id=tmdb_id,
                related_show_title=show_title,
                send_email=True  # Respects user preferences
            )

            logger.info(f"Sent series finale notification for {show_title}")

        elif new_status == "Canceled":
            # Cancellation notification
            num_seasons = status_info.get("number_of_seasons", 0)

            title = f"❌ Show Canceled: {show_title}"
            message = f"{show_title} has been canceled after {num_seasons} season{'s' if num_seasons != 1 else ''}."

            notifications.create_notification(
                client=client,
                user_id=user_id,
                notification_type="series_cancelled",
                title=title,
                message=message,
                related_show_id=tmdb_id,
                related_show_title=show_title,
                send_email=True  # Respects user preferences
            )

            logger.info(f"Sent cancellation notification for {show_title}")

    except Exception as e:
        logger.error(f"Error sending status change notification: {e}")


def check_all_shows_status(client: Client, user_id: str) -> Dict[str, int]:
    """
    Check status for all shows in user's watchlist

    Args:
        client: Supabase client
        user_id: User ID

    Returns:
        Dictionary with counts of updated, unchanged, and errors
    """
    try:
        # Get all shows for user
        result = client.table("shows")\
            .select("tmdb_id, title, show_status")\
            .eq("user_id", user_id)\
            .execute()

        if not result.data:
            return {"total": 0, "updated": 0, "unchanged": 0, "errors": 0}

        stats = {"total": len(result.data), "updated": 0, "unchanged": 0, "errors": 0}

        for show in result.data:
            tmdb_id = show["tmdb_id"]
            title = show["title"]
            old_status = show.get("show_status", "Unknown")

            new_status = update_show_status(client, user_id, tmdb_id, title)

            if new_status is None:
                stats["errors"] += 1
            elif new_status != old_status:
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1

        logger.info(f"Status check complete for user {user_id}: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Error checking all shows status: {e}")
        return {"total": 0, "updated": 0, "unchanged": 0, "errors": 1}


def is_series_finale(client: Client, user_id: str, tmdb_id: int, air_date: str) -> bool:
    """
    Check if an airing episode is a series finale

    Args:
        client: Supabase client
        user_id: User ID
        tmdb_id: TMDB show ID
        air_date: Episode air date

    Returns:
        True if this is the series finale, False otherwise
    """
    try:
        # Get show status
        result = client.table("shows")\
            .select("show_status")\
            .eq("user_id", user_id)\
            .eq("tmdb_id", tmdb_id)\
            .execute()

        if not result.data:
            return False

        status = result.data[0].get("show_status", "Unknown")

        # If show is Ended, check if this is the last episode
        if status in ["Ended", "Canceled"]:
            status_info = fetch_show_status(tmdb_id)
            if status_info:
                last_air_date = status_info.get("last_air_date")
                return last_air_date == air_date

        return False

    except Exception as e:
        logger.error(f"Error checking if series finale: {e}")
        return False


def get_show_status_emoji(status: str) -> str:
    """
    Get emoji for show status

    Args:
        status: Show status string

    Returns:
        Emoji representing the status
    """
    status_emojis = {
        "Returning Series": "📺",
        "Ended": "🎭",
        "Canceled": "❌",
        "In Production": "🎬",
        "Planned": "📅",
        "Pilot": "🚀",
        "Unknown": "❓"
    }
    return status_emojis.get(status, "❓")
