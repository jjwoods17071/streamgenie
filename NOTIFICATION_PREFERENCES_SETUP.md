# 🔔 Notification Preferences - Setup Guide

## ✅ What's Been Implemented

StreamGenie now has a **comprehensive user notification preferences system**! Users can customize exactly which notifications they want to receive via email and in-app.

### Features:
- ✅ Database table for storing user preferences
- ✅ 5 notification types users can control:
  - 🎬 New Episodes Airing
  - 📅 Weekly Preview
  - 🎭 Series Finales (coming soon)
  - ❌ Show Cancellations (coming soon)
  - ➕ Show Added to Watchlist
- ✅ Separate controls for email vs in-app notifications
- ✅ Beautiful UI in Settings > Notification Preferences tab
- ✅ All email sending respects user preferences
- ✅ Default preferences created automatically
- ✅ All notifications appear in sidebar

---

## 🚀 Deployment Steps

### Step 1: Run SQL Migration in Supabase

1. Open your Supabase dashboard: https://supabase.com/dashboard
2. Go to **SQL Editor**
3. Click **"New Query"**
4. Copy the entire contents of `create_notification_preferences.sql`
5. Click **"Run"**
6. ✅ You should see "Success. No rows returned"

This creates:
- `notification_preferences` table
- Row Level Security policies
- Indexes for performance
- `show_status` column in `shows` table (for future series status tracking)

### Step 2: Push Code to GitHub

The code is already committed locally. To push to GitHub:

```bash
# Push to GitHub
git push -u origin main
```

### Step 3: Wait for Auto-Deploy

Streamlit Cloud will automatically deploy within 1-2 minutes after you push.

### Step 4: Test Notification Preferences

1. Go to https://streamgenie-estero.streamlit.app
2. Login to your account
3. Go to **Settings** (⚙️ tab at bottom)
4. Click **"🔔 Notification Preferences"** tab
5. You should see:
   - **📧 Email Notifications** section (5 checkboxes)
   - **📱 In-App Notifications** section (5 checkboxes)
   - **💾 Save Preferences** button

Try:
- Uncheck "🎬 New Episodes Airing" under Email
- Click "💾 Save Preferences"
- You should see "✅ Notification preferences saved!" with balloons 🎉

---

## 📊 Database Schema

### notification_preferences Table

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | UUID | auto | Primary key |
| `user_id` | UUID | required | FK to auth.users |
| `email_new_episodes` | BOOLEAN | true | Email for new episodes |
| `email_weekly_preview` | BOOLEAN | true | Email for weekly previews |
| `email_series_finale` | BOOLEAN | true | Email for series finales |
| `email_series_cancelled` | BOOLEAN | true | Email for cancellations |
| `email_show_added` | BOOLEAN | false | Email when adding shows |
| `inapp_new_episodes` | BOOLEAN | true | In-app for new episodes |
| `inapp_weekly_preview` | BOOLEAN | true | In-app for weekly previews |
| `inapp_series_finale` | BOOLEAN | true | In-app for series finales |
| `inapp_series_cancelled` | BOOLEAN | true | In-app for cancellations |
| `inapp_show_added` | BOOLEAN | true | In-app when adding shows |
| `created_at` | TIMESTAMPTZ | NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NOW() | Last update timestamp |

**Security:** Row Level Security enabled - users can only view/edit their own preferences

---

## 🎯 How It Works

### When a Notification is Created

```python
# Example: Creating a new episode notification
notifications.create_notification(
    client=client,
    user_id=user_id,
    notification_type="new_episode",  # Maps to preferences
    title="New Episode Available!",
    message="Your show is airing today",
    related_show_id=12345,
    related_show_title="Stranger Things",
    send_email=True  # Will check user preferences
)
```

### What Happens Behind the Scenes

1. **Check In-App Preference:**
   - Look up `inapp_new_episodes` for this user
   - If `false`, skip creating in-app notification
   - If `true`, create notification in database

2. **Check Email Preference:**
   - If `send_email=True`, look up `email_new_episodes`
   - If user preference is `false`, don't send email
   - If user preference is `true`, send email via SendGrid

3. **Create Notification:**
   - Notification appears in sidebar (if in-app enabled)
   - Email sent to user (if email enabled)
   - User can mark as read or delete

---

## 🔧 Files Created/Modified

### New Files:

1. **`create_notification_preferences.sql`** (112 lines)
   - Database schema
   - RLS policies
   - Indexes
   - Adds `show_status` column to `shows` table

2. **`preferences.py`** (245 lines)
   - `get_user_preferences()` - Get user's preferences
   - `create_default_preferences()` - Create defaults for new users
   - `get_or_create_preferences()` - Get or create if missing
   - `update_preferences()` - Save user changes
   - `should_send_email()` - Check if email should be sent
   - `should_create_inapp_notification()` - Check if in-app should be created

### Modified Files:

3. **`app.py`**
   - Added `import preferences`
   - Added 4th tab: "🔔 Notification Preferences"
   - Created preferences UI with checkboxes
   - Save preferences button with balloons on success

4. **`notifications.py`**
   - Added `import preferences`
   - Updated `create_notification()` to check user preferences
   - Respects both in-app and email preferences

---

## 🎨 User Interface

### Notification Preferences Tab

**Location:** Settings > 🔔 Notification Preferences

**Layout:**
```
🔔 Customize Your Notifications
Choose which notifications you want to receive via email and in-app

### 📧 Email Notifications
Control which types of email notifications you receive

[Left Column]                    [Right Column]
☑️ 🎬 New Episodes Airing        ☑️ 📅 Weekly Preview
☑️ 🎭 Series Finales             ☑️ ❌ Show Cancellations
☐ ➕ Show Added to Watchlist

### 📱 In-App Notifications
Control which notifications appear in the sidebar

[Left Column]                    [Right Column]
☑️ 🎬 New Episodes Airing        ☑️ 📅 Weekly Preview
☑️ 🎭 Series Finales             ☑️ ❌ Show Cancellations
☑️ ➕ Show Added to Watchlist

[💾 Save Preferences]

💡 Tip: All notifications will appear in the sidebar notification center.
You can control which types trigger emails separately.
```

---

## 🧪 Testing Checklist

### Initial Setup
- [ ] Run `create_notification_preferences.sql` in Supabase
- [ ] Push code to GitHub
- [ ] Wait for Streamlit Cloud auto-deploy
- [ ] Navigate to deployed app

### Test Preferences UI
- [ ] Go to Settings > Notification Preferences
- [ ] See all 5 email notification checkboxes
- [ ] See all 5 in-app notification checkboxes
- [ ] All checkboxes have correct default values
- [ ] Change some preferences
- [ ] Click "Save Preferences"
- [ ] See success message with balloons
- [ ] Refresh page - preferences should persist

### Test Email Preferences
- [ ] Disable "Email: New Episodes"
- [ ] Save preferences
- [ ] Add a show with next_air_date = today
- [ ] Manually trigger daily reminders (Maintenance tab)
- [ ] Check email - should NOT receive email
- [ ] Check sidebar - should still see in-app notification

### Test In-App Preferences
- [ ] Disable "In-App: Show Added"
- [ ] Save preferences
- [ ] Add a new show to watchlist
- [ ] Check sidebar - should NOT see notification

---

## 🔮 Future Enhancements (Series Finale/Cancellation)

The UI already includes options for:
- 🎭 Series Finales
- ❌ Show Cancellations

These will work once we implement:

### TODO: Series Status Tracking
1. Add TMDB status checking (Returning Series, Ended, Cancelled)
2. Update `show_status` column when refreshing shows
3. Detect final episodes
4. Send notifications based on user preferences

**Implementation Plan:**
```python
# Get show details from TMDB
show_details = fetch_tmdb_show_details(tmdb_id)
status = show_details.get("status")  # "Returning Series", "Ended", "Canceled"

# Store in database
update_show_status(show_id, status)

# Create notification if changed to "Ended" or "Canceled"
if status in ["Ended", "Canceled"]:
    notifications.notify_series_status_change(
        client=client,
        user_id=user_id,
        show_title=title,
        show_id=tmdb_id,
        new_status=status,
        send_email=True  # Respects user preferences
    )
```

---

## 📈 Success Metrics

Track these to measure feature adoption:

- **Preference Changes:** How many users customize their preferences?
- **Disabled Notifications:** Which notification types do users disable most?
- **Email Open Rates:** Did customization increase engagement?
- **Support Tickets:** Fewer complaints about too many emails?

---

## 🎯 Key Benefits

### For Users:
- ✅ Full control over notification frequency
- ✅ Separate email and in-app preferences
- ✅ No unwanted emails
- ✅ Can still see all notifications in sidebar
- ✅ Preferences sync across devices

### For Development:
- ✅ Easy to add new notification types
- ✅ Preferences automatically checked
- ✅ Default preferences for new users
- ✅ Database-backed (not session-based)
- ✅ Scales to millions of users

### For Business:
- ✅ Reduced unsubscribe rate
- ✅ Higher email engagement
- ✅ Better user retention
- ✅ Professional feature set
- ✅ Competitive advantage

---

## 🐛 Troubleshooting

### Preferences Not Saving
**Symptom:** Clicking "Save Preferences" doesn't persist changes

**Cause:** notification_preferences table not created

**Fix:** Run `create_notification_preferences.sql` in Supabase

### Can't See Preferences Tab
**Symptom:** Only 3 tabs in Settings, no "Notification Preferences"

**Cause:** Old version of app.py deployed

**Fix:** Push code to GitHub and wait for auto-deploy

### Still Getting Emails After Disabling
**Symptom:** Emails arrive even though preference is disabled

**Cause:** Preferences not being checked by notifications module

**Fix:** Ensure `notifications.py` imports `preferences` module

### "Failed to save preferences" Error
**Symptom:** Error message when clicking Save

**Cause:** RLS policies not set up correctly

**Fix:** Check Supabase logs, ensure user is authenticated

---

## 📞 Next Steps

1. **Deploy Now:**
   - Run SQL migration
   - Push code to GitHub
   - Test in production

2. **Soon:**
   - Implement series status tracking from TMDB
   - Add series finale notifications
   - Add cancellation notifications

3. **Later:**
   - Add notification scheduling (quiet hours)
   - Add per-show notification preferences
   - Add notification digest mode (batch emails)

---

**Status:** ✅ Code Complete, Ready to Deploy

**Created:** 2025-11-03

**Files:**
- `create_notification_preferences.sql` - Database schema
- `preferences.py` - Preferences module
- `app.py` - UI implementation
- `notifications.py` - Respect user preferences
