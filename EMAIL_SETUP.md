# Email Reminder Setup Guide

StreamGenie now supports daily email reminders for shows airing today!

## Quick Setup

### 1. Get a Free SendGrid API Key

1. Sign up for a free SendGrid account at https://sendgrid.com/free/
2. Free tier includes **100 emails per day** (plenty for personal use)
3. Navigate to Settings > API Keys
4. Create a new API key with "Mail Send" permissions
5. Copy the API key (you'll only see it once!)

### 2. Set the Environment Variable

**Option A: For current session (Mac/Linux)**
```bash
export SENDGRID_API_KEY="your-api-key-here"
streamlit run app.py
```

**Option B: Permanent setup**

Create a `.env` file in the StreamGenie directory:
```bash
SENDGRID_API_KEY=your-api-key-here
TMDB_API_KEY=your-existing-tmdb-key
```

Then load it before running:
```bash
set -a; source .env; set +a
streamlit run app.py
```

**Option C: Add to your shell profile (Mac/Linux)**
```bash
echo 'export SENDGRID_API_KEY="your-api-key-here"' >> ~/.zshrc
source ~/.zshrc
streamlit run app.py
```

### 3. Configure in the App

1. Open StreamGenie at http://localhost:8501
2. Click the ⚙️ settings toggle
3. Go to the **📧 Email Reminders** tab
4. Enter your email address
5. Check "Enable"
6. Click "💾 Save Settings"
7. Click "📧 Test Email" to verify it works

### 4. Verify SendGrid Sender

**Important**: SendGrid requires sender verification for security.

1. Go to SendGrid Settings > Sender Authentication
2. Verify a Single Sender
3. Use the email: `notifications@streamgenie.app` OR your own email
4. Check your email and click the verification link

**Note**: If using a custom domain, you may need to verify it in SendGrid settings.

## How It Works

- **Daily Check**: At 8:00 AM every day, the app checks for shows airing today
- **Email Content**: Includes show title, poster image, streaming service, and air date
- **Privacy**: Your email is stored locally in `user_settings.json`

## Troubleshooting

### "SendGrid API key not configured"
- Make sure you set the `SENDGRID_API_KEY` environment variable
- Restart the Streamlit app after setting it

### "Failed to send test email"
- Check that your API key is valid
- Verify your sender email in SendGrid
- Check SendGrid Activity Feed for error details

### "Email not received"
- Check spam/junk folder
- Verify sender email is authenticated in SendGrid
- Test with a different email address

## Privacy & Security

- Your email is stored locally in `user_settings.json`
- API key is stored as environment variable (not in code)
- No data is sent to third parties except SendGrid for email delivery
- You can delete your email anytime from the settings

## Alternative: Manual Reminder Script

If you prefer not to use the background scheduler, you can set up a cron job:

Create `send_daily_reminders.py`:
```python
import sqlite3
import os
from app import check_and_send_daily_reminders, load_user_settings, get_conn

settings = load_user_settings()
if settings.get('reminders_enabled') and settings.get('email'):
    conn = get_conn()
    sent = check_and_send_daily_reminders(settings['email'], conn)
    print(f"Sent {sent} reminder emails")
    conn.close()
```

Then add to crontab:
```bash
0 8 * * * cd /path/to/StreamGenie && python send_daily_reminders.py
```

## Future Enhancements

Planned features:
- [ ] SMS reminders (Twilio integration)
- [ ] Custom reminder time
- [ ] Weekly digest emails
- [ ] Push notifications (web push)
- [ ] Reminder 1 hour before air time

---

**Questions or issues?** Open an issue on GitHub!
