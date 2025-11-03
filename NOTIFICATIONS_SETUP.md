# 🔔 Notifications System Setup Guide

## Overview

StreamGenie now has a comprehensive notifications system that provides:
- ✅ In-app notifications with beautiful UI
- ✅ Email notifications (via existing SendGrid integration)
- ✅ Unified notifications table
- ✅ Real-time notification badges
- ✅ Multiple notification types (new episodes, status changes, etc.)

## Step 1: Create the Notifications Table

1. Go to your Supabase dashboard: https://supabase.com/dashboard
2. Navigate to **SQL Editor**
3. Click **"New Query"**
4. Copy and paste the entire contents of `create_notifications_table.sql`
5. Click **"Run"**
6. You should see: "Success. No rows returned"

This creates:
- `notifications` table with all necessary columns
- Indexes for fast queries
- Row Level Security (RLS) policies
- Proper foreign key relationships

## Step 2: Verify the Table

1. Go to **Table Editor** in Supabase
2. You should see a new `notifications` table
3. Click on it to see the schema

Expected columns:
- `id` (uuid, primary key)
- `user_id` (uuid, foreign key to users table)
- `notification_type` (text: 'new_episode', 'reminder', 'status_change', 'system')
- `title` (text)
- `message` (text)
- `related_show_id` (integer, optional)
- `related_show_title` (text, optional)
- `is_read` (boolean, default false)
- `sent_email` (boolean, default false)
- `sent_push` (boolean, default false)
- `created_at` (timestamptz, default now())
- `read_at` (timestamptz, nullable)

## Step 3: Test the Notifications System

### Test 1: Add a New Show
1. Open http://localhost:8501
2. Search for a new TV show
3. Add it to your watchlist
4. ✅ You should see a notification in the sidebar: "Show Status Changed - [Show Name] has been added to your watchlist"

### Test 2: Check Notifications UI
1. Look at the sidebar
2. You should see: **🔔 Notifications** with a red badge showing unread count
3. Click "✓ Read" to mark as read
4. The badge count should decrease
5. Click "🗑️ Delete" to remove a notification

### Test 3: Email Reminders (Automated)
The daily reminder system automatically:
- Checks for shows airing today
- Creates in-app notifications
- Sends email reminders (if SendGrid is configured)

To test manually:
1. Set a show's `next_air_date` to today's date in the database
2. Run the daily reminder check (in the Maintenance tab)
3. ✅ You should receive both an email AND an in-app notification

## Notification Types

### 1. New Episode Notifications (🎬)
**When:** A show on your watchlist is airing today
**Created by:** `check_and_send_daily_reminders()` function
**Includes:** Email + in-app notification

### 2. Show Added Notifications (🔄)
**When:** You add a new show to your watchlist
**Created by:** `upsert_show()` function (only for new shows, not updates)
**Includes:** In-app notification only

### 3. Status Change Notifications (🔄)
**When:** A show's availability changes on your streaming service
**Created by:** Future feature - will be added when we implement status tracking
**Includes:** In-app notification (email optional)

### 4. System Notifications (ℹ️)
**When:** Important system messages (e.g., maintenance, new features)
**Created by:** Admin/system functions
**Includes:** In-app notification only

## Notification Features

### In the Sidebar
- **Badge Count**: Shows number of unread notifications
- **Mark as Read**: Click ✓ button to mark individual notification as read
- **Mark All as Read**: Button appears when you have unread notifications
- **Delete**: Click 🗑️ to remove a notification
- **Auto-refresh**: Notifications update when you interact with them
- **Time Stamps**: "Just now", "5 minutes ago", "Yesterday", etc.
- **Show Links**: Notifications link to related shows (shown in blue)

### Notification Styling
- **Unread**: Light blue background (#e3f2fd)
- **Read**: Gray background (#f0f2f6)
- **Left Border**: Purple accent (#667eea)
- **Type Emoji**: Visual indicator of notification type
- **Responsive**: Works on all screen sizes

## API Functions

### Create Notification
```python
import notifications

# Create a custom notification
notifications.create_notification(
    client=client,
    user_id="user-uuid",
    notification_type="system",
    title="Welcome to StreamGenie!",
    message="Your account has been verified.",
    send_email=False
)
```

### Get User Notifications
```python
# Get all notifications
notifs = notifications.get_user_notifications(
    client=client,
    user_id="user-uuid",
    unread_only=False,
    limit=50
)

# Get only unread
unread = notifications.get_user_notifications(
    client=client,
    user_id="user-uuid",
    unread_only=True
)
```

### Mark as Read
```python
# Mark one notification as read
notifications.mark_notification_read(client, notification_id)

# Mark all as read
notifications.mark_all_notifications_read(client, user_id)
```

### Get Unread Count
```python
count = notifications.get_unread_count(client, user_id)
print(f"You have {count} unread notifications")
```

### Notify New Episode
```python
notifications.notify_new_episode(
    client=client,
    user_id="user-uuid",
    show_title="Stranger Things",
    show_id=66732,
    air_date="2025-11-03",
    send_email=True  # Also send email
)
```

### Notify Status Change
```python
notifications.notify_show_status_change(
    client=client,
    user_id="user-uuid",
    show_title="The Office",
    show_id=2316,
    new_status="available",  # 'available', 'unavailable', 'added'
    send_email=False
)
```

## Database Schema

```sql
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    related_show_id INTEGER,
    related_show_title TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    sent_email BOOLEAN DEFAULT FALSE,
    sent_push BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    read_at TIMESTAMPTZ
);
```

## Row Level Security (RLS) Policies

The notifications table has the following RLS policies:

1. **Users can view own notifications**: Users can only SELECT their own notifications
2. **Users can update own notifications**: Users can mark their notifications as read
3. **System can insert notifications**: Backend can create notifications for any user
4. **Users can delete own notifications**: Users can delete their notifications

These policies ensure data isolation and security in a multi-user environment.

## Future Enhancements

### 🔮 Planned Features
1. **Push Notifications**: Browser push notifications using Web Push API
2. **Supabase Realtime**: Live updates without page refresh
3. **Notification Preferences**: Per-user settings (email on/off, types, frequency)
4. **Notification Center**: Dedicated page with filters and search
5. **Batch Notifications**: "3 shows airing this week" summary
6. **Notification Actions**: "Mark as watched", "Add reminder" buttons
7. **Rich Notifications**: Images, trailers, links in notifications

### Implementation Notes for Realtime

Supabase Realtime would enable instant notification updates without refreshing. Here's how to add it:

```python
# Example realtime subscription (requires realtime-py package)
def subscribe_to_notifications(client, user_id, callback):
    """Subscribe to realtime notification updates"""
    client.table("notifications")\
        .on("INSERT", callback)\
        .filter(f"user_id=eq.{user_id}")\
        .subscribe()
```

For Streamlit, we could:
- Use `st.rerun()` with polling intervals
- Implement WebSocket connection in JavaScript
- Use iframe with realtime updates

## Troubleshooting

### Notifications not appearing?
1. Check that the notifications table was created successfully
2. Verify RLS policies are in place
3. Check browser console for errors
4. Ensure user_id is correct

### Unread count not updating?
1. Refresh the page (Streamlit limitation)
2. Check that `mark_notification_read()` is being called
3. Verify the notification ID is correct

### Email not sending?
1. Check SendGrid API key is set in .env
2. Verify SendGrid sender email is verified
3. Check spam folder
4. Look for errors in console/logs

### Notifications table doesn't exist?
1. Run the SQL script in Supabase SQL Editor
2. Check for syntax errors in the script
3. Verify you're connected to the right database

## Files Created

- `notifications.py` - Notifications module with all functions
- `create_notifications_table.sql` - Database schema script
- `NOTIFICATIONS_SETUP.md` - This file

## Changes to Existing Files

### `app.py`
1. Added `import notifications`
2. Added `notifications.render_notifications_ui(client, get_user_id())` after auth menu
3. Updated `upsert_show()` to create notification for new shows
4. Updated `check_and_send_daily_reminders()` to create in-app notifications

### No other changes needed!
The notifications system integrates seamlessly with your existing authentication and database structure.

---

**Status**: Ready to test! 🚀
**Date**: 2025-11-03
**Next Step**: Run the SQL script and start testing!
