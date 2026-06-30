"""
Notifications module for StreamGenie
Handles in-app notifications, email notifications, and realtime updates
"""
import streamlit as st
from supabase import Client
from typing import Optional, List, Dict, Any
from datetime import datetime
import html
import mailer
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
            # Idempotency: don't insert a duplicate. The daily-reminder routine can run more
            # than once (cron + manual triggers + reruns), so guard on the natural key
            # (user, type, show, message) — e.g. "new episode airing on 2026-06-03" for one
            # show should exist at most once.
            try:
                dup = client.table("notifications").select("id")\
                    .eq("user_id", user_id)\
                    .eq("notification_type", notification_type)\
                    .eq("message", message)
                if related_show_id is not None:
                    dup = dup.eq("related_show_id", related_show_id)
                if dup.limit(1).execute().data:
                    return True  # already exists → skip insert and email
            except Exception:
                pass  # if the dedup check fails, fall through and insert

            notification_data = {
                "user_id": user_id,
                "notification_type": notification_type,
                "title": title,
                "message": message,
                "related_show_id": related_show_id,
                "related_show_title": related_show_title,
                "sent_email": should_email
            }

            # Atomic claim: the pre-check above can't stop CONCURRENT writers (several
            # app instances firing the 8 AM job in the same second all pass it before
            # any insert lands). With the notifications_dedup_idx unique index
            # (migrations/2026-06-04_notifications_unique.sql), upsert+ignore_duplicates
            # returns the row only to the ONE winner — losers get [] and skip the email.
            try:
                ins = client.table("notifications").upsert(
                    notification_data,
                    on_conflict="user_id,notification_type,related_show_id,message",
                    ignore_duplicates=True
                ).execute()
                if not ins.data:
                    return True  # another instance already created it → no email
            except Exception:
                # Unique index not created yet → plain insert (pre-check still
                # blocks sequential dupes; concurrent dupes possible until migration runs)
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

        # Email transport configured? (SMTP via mailer — Postmark/Gmail/etc.)
        if not mailer.is_configured():
            print("Email not configured")
            return

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

        if mailer.send_email(user_email, subject, html_content):
            print(f"Email sent to {user_email}")
        else:
            print(f"Email send failed for {user_email}")

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


def render_notifications_panel(client: Client, user_id: str, key_prefix: str = ""):
    """Render the notifications list (header, mark-all, items) into the current container.
    Container-agnostic so it works in the sidebar OR a header popover. key_prefix keeps
    widget keys unique when the panel is rendered in more than one place."""
    unread_count = get_unread_count(client, user_id)

    # Notifications header with badge
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("### 🔔 Notifications")
    with col2:
        if unread_count > 0:
            st.markdown(f"<span style='background-color: #ff4b4b; color: white; padding: 4px 8px; border-radius: 12px; font-size: 12px; font-weight: bold;'>{unread_count}</span>", unsafe_allow_html=True)

    notifications = get_user_notifications(client, user_id, unread_only=False, limit=10)

    if not notifications:
        st.info("No notifications yet")
        return

    # Mark all as read button
    if unread_count > 0:
        if st.button("✓ Mark all as read", use_container_width=True, key=f"{key_prefix}mark_all"):
            mark_all_notifications_read(client, user_id)
            st.rerun()

    # Display notifications
    for notification in notifications:
        with st.container():
            bg_color = "#f0f2f6" if notification["is_read"] else "#e3f2fd"
            type_emoji = {
                "new_episode": "🎬",
                "reminder": "⏰",
                "status_change": "🔄",
                "system": "ℹ️"
            }.get(notification["notification_type"], "📢")

            # Escape dynamic text so titles/messages can't break the layout or inject markup.
            title_html = html.escape(notification['title'] or "")
            message_html = html.escape(notification['message'] or "")
            time_html = html.escape(format_notification_time(notification['created_at']))
            show_line = ""
            if notification.get("related_show_title"):
                show_title_html = html.escape(notification["related_show_title"])
                show_line = (
                    f'<p style="margin: 4px 0 0 0; font-size: 12px; color: #667eea;">'
                    f'📺 {show_title_html}</p>'
                )

            # Single-line HTML rendered via st.html() — no Markdown pass, so an empty
            # optional line can't terminate the block early and leak raw tags as text.
            card_html = (
                f'<div style="background-color: {bg_color}; padding: 12px; border-radius: 8px; '
                f'margin-bottom: 8px; border-left: 4px solid #667eea;">'
                f'<div style="display: flex; align-items: start; justify-content: space-between;">'
                f'<div style="flex: 1;">'
                f'<strong>{type_emoji} {title_html}</strong>'
                f'<p style="margin: 4px 0 0 0; font-size: 14px; color: #666;">{message_html}</p>'
                f'{show_line}'
                f'<p style="margin: 4px 0 0 0; font-size: 12px; color: #999;">{time_html}</p>'
                f'</div></div></div>'
            )
            st.html(card_html)

            col1, col2 = st.columns([1, 1])
            with col1:
                if not notification["is_read"]:
                    if st.button("✓ Read", key=f"{key_prefix}read_{notification['id']}", use_container_width=True):
                        mark_notification_read(client, notification["id"])
                        st.rerun()
            with col2:
                if st.button("🗑️ Delete", key=f"{key_prefix}delete_{notification['id']}", use_container_width=True):
                    delete_notification(client, notification["id"])
                    st.rerun()


def render_notifications_ui(client: Client, user_id: str):
    """Render the notifications UI in the sidebar"""
    with st.sidebar:
        st.markdown("---")
        render_notifications_panel(client, user_id, key_prefix="sb_")


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
    send_email: bool = False
):
    """Create notification for new episode (bell only by default — see newsletter.py)"""
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


def notify_airing_digest(client: Client, user_id: str, shows: list):
    """ONE consolidated in-app notification for all of a user's shows airing today.

    Bell only — no email. The weekly newsletter (newsletter.py) is the single
    email surface; day-of nudges live in the notification bell.
    `shows` are rows from the shows table (title, provider_name, next_air_date).
    Only called on days when something actually airs — no empty digests.
    """
    if not shows:
        return

    def _label(s):
        p = (s.get("provider_name") or "").strip()
        return f"{s['title']} ({p})" if p and p != "Multiple Providers" else s["title"]

    air_date = shows[0].get("next_air_date", "")
    n = len(shows)
    create_notification(
        client=client,
        user_id=user_id,
        notification_type="new_episode",
        title="New Episode Today" if n == 1 else f"{n} Shows Airing Today",
        message=f"New episode{'s' if n > 1 else ''} on {air_date}: " +
                ", ".join(_label(s) for s in shows),
        # Sentinel 0 (not NULL): the dedup unique index treats NULLs as distinct,
        # so NULL digests race past it — a real value makes the atomic claim work.
        related_show_id=0,
        related_show_title=", ".join(s["title"] for s in shows),
        send_email=False  # weekly newsletter is the only email
    )


def expire_stale_airing(client: Client) -> int:
    """Delete airing notifications whose air date has passed — the episodes now
    live in Catch Up, so the bell shouldn't keep announcing them. Returns count."""
    import re as _re
    import datetime as _dt
    today = _dt.date.today().isoformat()
    try:
        rows = client.table("notifications").select("id,message")\
            .eq("notification_type", "new_episode").execute().data or []
        stale = [x["id"] for x in rows
                 if (m := _re.search(r"(\d{4}-\d{2}-\d{2})", x.get("message") or ""))
                 and m.group(1) < today]
        for i in range(0, len(stale), 50):
            client.table("notifications").delete().in_("id", stale[i:i+50]).execute()
        return len(stale)
    except Exception as e:
        print(f"Error expiring stale notifications: {e}")
        return 0


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
