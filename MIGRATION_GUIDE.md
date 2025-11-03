# Supabase Migration Guide

This guide will walk you through migrating StreamGenie from SQLite to PostgreSQL (Supabase).

## ✅ Prerequisites

- [ ] Supabase account created
- [ ] New project created in Supabase
- [ ] Project URL and API key obtained

## Step 1: Create Supabase Account & Project

1. **Go to** https://supabase.com and click "Start your project"
2. **Sign up** with GitHub or email
3. **Create a new organization** (if first time)
4. **Create a new project:**
   - Name: `streamgenie`
   - Database Password: **Save this somewhere safe!**
   - Region: Choose closest (e.g., `us-east-1`)
   - Plan: **Free** (500MB, 50K MAU)
5. **Wait 2-3 minutes** for provisioning

## Step 2: Get Your Credentials

1. In Supabase, go to **Project Settings** (gear icon) → **API**
2. Copy these values:
   ```
   Project URL: https://xxxxxxxxxxxxx.supabase.co
   anon/public key: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   ```

## Step 3: Update .env File

Add the Supabase credentials to your `.env` file:

```bash
# Open .env file
open -e .env

# Add these lines:
SUPABASE_URL=https://xxxxxxxxxxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

Your complete `.env` should now have:
```env
TMDB_API_KEY=98e894f9b6ee5fe7439016b9226fb588
SENDGRID_API_KEY=SG.RGjXx_eXRfGNtpERd0ueXQ.G30FF0lduIXdBr233tfsAR6sS7M8o0bR__oGrTO54Io
SENDGRID_FROM_EMAIL=joe@outdoorkitchenstore.com
SUPABASE_URL=https://xxxxxxxxxxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## Step 4: Run Database Schema

1. In Supabase, go to **SQL Editor** (left sidebar)
2. Click **"New query"**
3. Copy the entire contents of `supabase_schema.sql`
4. Paste into the SQL Editor
5. Click **"Run"** (or press Cmd/Ctrl + Enter)

You should see:
```
Success. No rows returned
```

This creates all the tables, indexes, and security policies.

## Step 5: Verify Schema

1. Go to **Table Editor** in Supabase
2. You should see these tables:
   - `users`
   - `user_settings`
   - `shows`
   - `logo_overrides`
   - `deleted_providers`

## Step 6: Run Migration Script

Run the migration script to copy data from SQLite to Supabase:

```bash
python migrate_to_supabase.py
```

You should see output like:
```
==================================================
🚀 StreamGenie SQLite → Supabase Migration
==================================================

🔗 Connecting to Supabase...
📂 Reading from SQLite database: shows.db
📊 Found 5 shows in SQLite database

📺 Migrating shows...
  ✅ Migrated: Breaking Bad
  ✅ Migrated: Stranger Things
  ✅ Migrated: The Last of Us
  ...

✅ Shows migrated: 5/5
```

## Step 7: Verify Migration

1. In Supabase **Table Editor**, click on `shows` table
2. You should see all your shows migrated
3. Check `logo_overrides` and `deleted_providers` tables too

## Step 8: Test Connection

Test that the app can connect to Supabase:

```bash
python -c "from supabase import create_client; import os; from dotenv import load_dotenv; load_dotenv(); client = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY')); print('✅ Connected to Supabase!'); print(f'Shows count: {len(client.table(\"shows\").select(\"*\").execute().data)}')"
```

Should output:
```
✅ Connected to Supabase!
Shows count: 5
```

## Step 9: Update app.py (Next Step)

Once migration is complete and verified, we'll update `app.py` to use Supabase instead of SQLite.

## Rollback Plan

If something goes wrong, you can always:

1. **Keep using SQLite** - Your original `shows.db` is untouched
2. **Delete Supabase project** - Go to Project Settings → General → Delete Project
3. **Try again** - Create a new project and re-run migration

## Troubleshooting

### Error: "SUPABASE_URL not set"
- Make sure you added credentials to `.env` file
- Run: `source .env` before running migration

### Error: "Failed to migrate show"
- Check Supabase logs in Dashboard → Logs
- Verify schema was created correctly
- Check for constraint violations (duplicate shows)

### Error: "Connection refused"
- Wait a few minutes - project might still be provisioning
- Check Project Status in Supabase dashboard

## Next Steps

After successful migration:
- [ ] Update `app.py` to use Supabase
- [ ] Add user authentication
- [ ] Test all features
- [ ] Deploy!

---

**Need help?** Check the Supabase docs: https://supabase.com/docs
