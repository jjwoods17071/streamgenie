"""
Notification Preferences Management
Handles user preferences for email and in-app notifications
"""
from supabase import Client
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


def get_user_preferences(client: Client, user_id: str) -> Optional[Dict]:
    """
    Get notification preferences for a user

    Args:
        client: Supabase client
        user_id: User UUID

    Returns:
        Dictionary of preferences or None if not found
    """
    try:
        result = client.table("notification_preferences")\
            .select("*")\
            .eq("user_id", user_id)\
            .execute()

        if result.data and len(result.data) > 0:
            return result.data[0]

        # Return defaults if no preferences exist
        return None
    except Exception as e:
        logger.error(f"Error getting user preferences: {e}")
        return None


def create_default_preferences(client: Client, user_id: str) -> Dict:
    """
    Create default notification preferences for a new user

    Args:
        client: Supabase client
        user_id: User UUID

    Returns:
        Created preferences dictionary
    """
    try:
        defaults = {
            "user_id": user_id,
            "email_new_episodes": True,
            "email_weekly_preview": True,
            "email_series_finale": True,
            "email_series_cancelled": True,
            "email_show_added": False,
            "inapp_new_episodes": True,
            "inapp_weekly_preview": True,
            "inapp_series_finale": True,
            "inapp_series_cancelled": True,
            "inapp_show_added": True,
            "daily_reminder_time": "08:00:00",
            "weekly_preview_day": "Sunday",
            "weekly_preview_time": "18:00:00",
            "timezone": "America/New_York"
        }

        result = client.table("notification_preferences")\
            .insert(defaults)\
            .execute()

        if result.data and len(result.data) > 0:
            logger.info(f"Created default preferences for user {user_id}")
            return result.data[0]

        return defaults
    except Exception as e:
        logger.error(f"Error creating default preferences: {e}")
        return defaults


def get_or_create_preferences(client: Client, user_id: str) -> Dict:
    """
    Get user preferences, creating defaults if they don't exist

    Args:
        client: Supabase client
        user_id: User UUID

    Returns:
        Preferences dictionary
    """
    prefs = get_user_preferences(client, user_id)
    if prefs is None:
        prefs = create_default_preferences(client, user_id)
    return prefs


def update_preferences(client: Client, user_id: str, updates: Dict) -> bool:
    """
    Update user notification preferences

    Args:
        client: Supabase client
        user_id: User UUID
        updates: Dictionary of preference keys to update

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if preferences exist
        existing = get_user_preferences(client, user_id)

        if existing is None:
            # Create new preferences with updates
            defaults = {
                "user_id": user_id,
                "email_new_episodes": True,
                "email_weekly_preview": True,
                "email_series_finale": True,
                "email_series_cancelled": True,
                "email_show_added": False,
                "inapp_new_episodes": True,
                "inapp_weekly_preview": True,
                "inapp_series_finale": True,
                "inapp_series_cancelled": True,
                "inapp_show_added": True,
                "daily_reminder_time": "08:00:00",
                "weekly_preview_day": "Sunday",
                "weekly_preview_time": "18:00:00",
                "timezone": "America/New_York"
            }
            defaults.update(updates)

            result = client.table("notification_preferences")\
                .insert(defaults)\
                .execute()
        else:
            # Update existing preferences
            result = client.table("notification_preferences")\
                .update(updates)\
                .eq("user_id", user_id)\
                .execute()

        logger.info(f"Updated preferences for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error updating preferences: {e}")
        return False


def should_send_email(client: Client, user_id: str, notification_type: str) -> bool:
    """
    Check if an email should be sent based on user preferences

    Args:
        client: Supabase client
        user_id: User UUID
        notification_type: Type of notification (new_episodes, weekly_preview, series_finale, etc.)

    Returns:
        True if email should be sent, False otherwise
    """
    try:
        prefs = get_or_create_preferences(client, user_id)

        # Map notification types to preference keys
        type_mapping = {
            "new_episode": "email_new_episodes",
            "new_episodes": "email_new_episodes",
            "weekly_preview": "email_weekly_preview",
            "series_finale": "email_series_finale",
            "series_cancelled": "email_series_cancelled",
            "show_added": "email_show_added",
            "status_change": "email_show_added"  # Map status_change to show_added
        }

        pref_key = type_mapping.get(notification_type, None)

        if pref_key is None:
            # Unknown type, default to not sending email
            logger.warning(f"Unknown notification type: {notification_type}")
            return False

        return prefs.get(pref_key, False)
    except Exception as e:
        logger.error(f"Error checking email preference: {e}")
        return False


def should_create_inapp_notification(client: Client, user_id: str, notification_type: str) -> bool:
    """
    Check if an in-app notification should be created based on user preferences

    Args:
        client: Supabase client
        user_id: User UUID
        notification_type: Type of notification

    Returns:
        True if in-app notification should be created, False otherwise
    """
    try:
        prefs = get_or_create_preferences(client, user_id)

        # Map notification types to preference keys
        type_mapping = {
            "new_episode": "inapp_new_episodes",
            "new_episodes": "inapp_new_episodes",
            "weekly_preview": "inapp_weekly_preview",
            "series_finale": "inapp_series_finale",
            "series_cancelled": "inapp_series_cancelled",
            "show_added": "inapp_show_added",
            "status_change": "inapp_show_added"
        }

        pref_key = type_mapping.get(notification_type, None)

        if pref_key is None:
            # Unknown type, default to creating notification
            return True

        return prefs.get(pref_key, True)
    except Exception as e:
        logger.error(f"Error checking in-app preference: {e}")
        return True  # Default to showing notifications on error
