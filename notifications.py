"""
Notifications module for StreamGenie
Handles in-app notifications, email notifications, and realtime updates
"""
import streamlit as st
from supabase import Client
from typing import Optional, List, Dict, Any
from datetime import datetime
import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content
import os
import preferences  # User notification preferences


def create_notification(
    client: Client,
    user_id: str,
    notification_type: str,
    title: str,
    message: str,
    related_show_id: Optional[int] = None,
    related_show_title: Optional[str] = None,
    send_email: bool = False
) -> bool:
    """
    Create a new notification

    Args:
        client: Supabase client
        user_id: User ID to send notification to
        notification_type: Type of notification ('new_episode', 'reminder', 'status_change', 'system')
        title: Notification title
        message: Notification message
        related_show_id: Optional TMDB show ID
        related_show_title: Optional show title
        send_email: Whether to also send an email

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check user preferences for in-app notifications
        should_create_inapp = preferences.should_create_inapp_notification(client, user_id, notification_type)

        if not should_create_inapp and not send_email:
            # User disabled this notification type
            return True

        # Check user preferences for email
        should_email = send_email and preferences.should_send_email(client, user_id, notification_type)

        # Create in-app notification if user hasn't disabled it
        if should_create_inapp:
            notification_data = {
                "user_id": user_id,
                "notification_type": notification_type,
                "title": title,
                "message": message,
                "related_show_id": related_show_id,
                "related_show_title": related_show_title,
                "sent_email": should_email
            }

            client.table("notifications").insert(notification_data).execute()

        # Send email if user preferences allow
        if should_email:
            send_notification_email(client, user_id, title, message, related_show_title)

        return True
    except Exception as e:
        print(f"Error creating notification: {e}")
        return False


def send_notification_email(
    client: Client,
    user_id: str,
    title: str,
    message: str,
    show_title: Optional[str] = None
):
    """Send notification via email using SendGrid"""
    try:
        # Get user email
        result = client.table("users").select("email").eq("id", user_id).execute()
        if not result.data:
            return

        user_email = result.data[0]["email"]

        # Get SendGrid API key
        sg_api_key = os.getenv("SENDGRID_API_KEY")
        if not sg_api_key:
            print("SendGrid API key not found")
            return

        sg = sendgrid.SendGridAPIClient(api_key=sg_api_key)

        # Build email content
        subject = f"StreamGenie: {title}"

        if show_title:
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 28px;">🍿 StreamGenie</h1>
                </div>
                <div style="background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px;">
                    <h2 style="color: #333; margin-top: 0;">{title}</h2>
                    <p style="color: #666; font-size: 16px; line-height: 1.6;">{message}</p>
                    <div style="background: white; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <p style="margin: 0; color: #667eea; font-weight: bold; font-size: 18px;">📺 {show_title}</p>
                    </div>
                    <p style="color: #999; font-size: 14px; margin-top: 30px; text-align: center;">
                        Sent by StreamGenie - Your personal streaming tracker
                    </p>
                </div>
            </body>
            </html>
            """
        else:
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 28px;">🍿 StreamGenie</h1>
                </div>
                <div style="background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px;">
                    <h2 style="color: #333; margin-top: 0;">{title}</h2>
                    <p style="color: #666; font-size: 16px; line-height: 1.6;">{message}</p>
                    <p style="color: #999; font-size: 14px; margin-top: 30px; text-align: center;">
                        Sent by StreamGenie - Your personal streaming tracker
                    </p>
                </div>
            </body>
            </html>
            """

        from_email = Email("joe@outdoorkitchenstore.com")
        to_email = To(user_email)
        content = Content("text/html", html_content)

        mail = Mail(from_email, to_email, subject, content)
        mail.reply_to = Email("jjwoods@gmail.com")

        sg.send(mail)
        print(f"Email sent to {user_email}")

    except Exception as e:
        print(f"Error sending email: {e}")


def get_user_notifications(
    client: Client,
    user_id: str,
    unread_only: bool = False,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Get notifications for a user

    Args:
        client: Supabase client
        user_id: User ID
        unread_only: If True, only return unread notifications
        limit: Maximum number of notifications to return

    Returns:
        List of notification dictionaries
    """
    try:
        query = client.table("notifications")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(limit)

        if unread_only:
            query = query.eq("is_read", False)

        result = query.execute()
        return result.data
    except Exception as e:
        print(f"Error fetching notifications: {e}")
        return []


def mark_notification_read(client: Client, notification_id: str) -> bool:
    """Mark a notification as read"""
    try:
        client.table("notifications")\
            .update({"is_read": True, "read_at": datetime.now().isoformat()})\
            .eq("id", notification_id)\
            .execute()
        return True
    except Exception as e:
        print(f"Error marking notification as read: {e}")
        return False


def mark_all_notifications_read(client: Client, user_id: str) -> bool:
    """Mark all notifications for a user as read"""
    try:
        client.table("notifications")\
            .update({"is_read": True, "read_at": datetime.now().isoformat()})\
            .eq("user_id", user_id)\
            .eq("is_read", False)\
            .execute()
        return True
    except Exception as e:
        print(f"Error marking all notifications as read: {e}")
        return False


def delete_notification(client: Client, notification_id: str) -> bool:
    """Delete a notification"""
    try:
        client.table("notifications")\
            .delete()\
            .eq("id", notification_id)\
            .execute()
        return True
    except Exception as e:
        print(f"Error deleting notification: {e}")
        return False


def get_unread_count(client: Client, user_id: str) -> int:
    """Get count of unread notifications"""
    try:
        result = client.table("notifications")\
            .select("id", count="exact")\
            .eq("user_id", user_id)\
            .eq("is_read", False)\
            .execute()
        return result.count if result.count else 0
    except Exception as e:
        print(f"Error getting unread count: {e}")
        return 0


def render_notifications_ui(client: Client, user_id: str):
    """Render the notifications UI in the sidebar"""

    # Get unread count
    unread_count = get_unread_count(client, user_id)

    with st.sidebar:
        st.markdown("---")

        # Notifications header with badge
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("### 🔔 Notifications")
        with col2:
            if unread_count > 0:
                st.markdown(f"<span style='background-color: #ff4b4b; color: white; padding: 4px 8px; border-radius: 12px; font-size: 12px; font-weight: bold;'>{unread_count}</span>", unsafe_allow_html=True)

        # Get notifications
        notifications = get_user_notifications(client, user_id, unread_only=False, limit=10)

        if not notifications:
            st.info("No notifications yet")
        else:
            # Mark all as read button
            if unread_count > 0:
                if st.button("✓ Mark all as read", use_container_width=True):
                    mark_all_notifications_read(client, user_id)
                    st.rerun()

            # Display notifications
            for notification in notifications:
                with st.container():
                    # Notification styling based on read status
                    bg_color = "#f0f2f6" if notification["is_read"] else "#e3f2fd"

                    # Notification type emoji
                    type_emoji = {
                        "new_episode": "🎬",
                        "reminder": "⏰",
                        "status_change": "🔄",
                        "system": "ℹ️"
                    }.get(notification["notification_type"], "📢")

                    st.markdown(f"""
                    <div style="background-color: {bg_color}; padding: 12px; border-radius: 8px; margin-bottom: 8px; border-left: 4px solid #667eea;">
                        <div style="display: flex; align-items: start; justify-content: space-between;">
                            <div style="flex: 1;">
                                <strong>{type_emoji} {notification['title']}</strong>
                                <p style="margin: 4px 0 0 0; font-size: 14px; color: #666;">{notification['message']}</p>
                                {f'<p style="margin: 4px 0 0 0; font-size: 12px; color: #667eea;">📺 {notification["related_show_title"]}</p>' if notification.get("related_show_title") else ''}
                                <p style="margin: 4px 0 0 0; font-size: 12px; color: #999;">{format_notification_time(notification['created_at'])}</p>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    # Action buttons
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        if not notification["is_read"]:
                            if st.button("✓ Read", key=f"read_{notification['id']}", use_container_width=True):
                                mark_notification_read(client, notification["id"])
                                st.rerun()
                    with col2:
                        if st.button("🗑️ Delete", key=f"delete_{notification['id']}", use_container_width=True):
                            delete_notification(client, notification["id"])
                            st.rerun()


def format_notification_time(timestamp_str: str) -> str:
    """Format notification timestamp for display"""
    try:
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        now = datetime.now(timestamp.tzinfo)
        diff = now - timestamp

        if diff.days == 0:
            if diff.seconds < 60:
                return "Just now"
            elif diff.seconds < 3600:
                minutes = diff.seconds // 60
                return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
            else:
                hours = diff.seconds // 3600
                return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif diff.days == 1:
            return "Yesterday"
        elif diff.days < 7:
            return f"{diff.days} days ago"
        else:
            return timestamp.strftime("%b %d, %Y")
    except Exception:
        return timestamp_str


def notify_new_episode(
    client: Client,
    user_id: str,
    show_title: str,
    show_id: int,
    air_date: str,
    send_email: bool = True
):
    """Create notification for new episode"""
    create_notification(
        client=client,
        user_id=user_id,
        notification_type="new_episode",
        title="New Episode Available!",
        message=f"A new episode is airing on {air_date}",
        related_show_id=show_id,
        related_show_title=show_title,
        send_email=send_email
    )


def notify_show_status_change(
    client: Client,
    user_id: str,
    show_title: str,
    show_id: int,
    new_status: str,
    send_email: bool = False
):
    """Create notification for show status change"""
    status_messages = {
        "available": f"{show_title} is now available on your streaming service!",
        "unavailable": f"{show_title} is no longer available on your streaming service.",
        "added": f"{show_title} has been added to your watchlist."
    }

    create_notification(
        client=client,
        user_id=user_id,
        notification_type="status_change",
        title="Show Status Changed",
        message=status_messages.get(new_status, f"Status changed for {show_title}"),
        related_show_id=show_id,
        related_show_title=show_title,
        send_email=send_email
    )


# Realtime subscription functions
def init_realtime_notifications(client: Client, user_id: str):
    """
    Initialize Supabase Realtime subscription for notifications
    NOTE: This requires the realtime-py package and works best with async
    For Streamlit, we'll use polling instead in the main app
    """
    # Realtime subscriptions work best in async contexts
    # For Streamlit, we'll implement a polling mechanism in app.py
    pass
