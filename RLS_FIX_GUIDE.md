# Row Level Security (RLS) Fix Guide

## The Problem

You're seeing this error when trying to add shows:
```
'message': 'new row violates row-level security policy for table "shows"'
```

This happens because:
1. The Supabase schema enables RLS (Row Level Security) on all tables
2. You're using the `anon` (public) API key
3. RLS blocks the `anon` key from inserting data without authentication

## Solution Options

### ✅ Option 1: Use Service Role Key (RECOMMENDED)

**Best for:** Development and single-user apps

The service_role key bypasses RLS automatically, so no database changes needed.

**Steps:**
1. Go to Supabase Dashboard → Settings → API
2. Find the **service_role key** (labeled "secret")
3. Copy the service_role key
4. Update `.env` line 22:
   ```env
   SUPABASE_KEY=<paste-service-role-key-here>
   ```
5. Restart the app

**Pros:**
- ✅ No database schema changes needed
- ✅ Works immediately
- ✅ Can still use RLS in the future when you add auth
- ✅ Secure for local/backend apps

**Cons:**
- ⚠️ Must never be exposed in client-side code (but your Streamlit app is server-side, so it's safe!)

---

### Option 2: Disable RLS in Database

**Best for:** Quick testing if you don't have access to service_role key

**Steps:**
1. Go to Supabase Dashboard → SQL Editor
2. Run this SQL:
   ```sql
   ALTER TABLE shows DISABLE ROW LEVEL SECURITY;
   ALTER TABLE logo_overrides DISABLE ROW LEVEL SECURITY;
   ALTER TABLE deleted_providers DISABLE ROW LEVEL SECURITY;
   ALTER TABLE user_settings DISABLE ROW LEVEL SECURITY;
   ```
3. App will work immediately

**Pros:**
- ✅ Quick fix
- ✅ Works with anon key

**Cons:**
- ⚠️ Removes security layer (not ideal for production)
- ⚠️ Need to re-enable RLS later when adding auth

---

## Key Comparison

| Key Type | RLS Behavior | Use Case |
|----------|--------------|----------|
| **anon** (public) | ✅ RLS Enforced | Frontend apps with user authentication |
| **service_role** (secret) | ❌ RLS Bypassed | Backend operations, admin tools, single-user apps |

## Current Status

- ✅ App running successfully at http://localhost:8501
- ✅ Watchlist displays correctly (reads work)
- ❌ Cannot add shows (inserts blocked by RLS)
- ✅ Maintenance tab now loads without errors

## Next Steps

1. Choose Option 1 or Option 2 above
2. Test adding a show to your watchlist
3. Verify all features work correctly

## Future: Multi-User with Authentication

When you're ready to add Supabase Auth for multiple users:

1. **Add authentication:** Implement Supabase Auth (signup/login)
2. **Update queries:** Replace `DEFAULT_USER_ID` with `auth.uid()`
3. **Re-enable RLS:** Turn RLS back on (or leave it on if using service_role)
4. **Update policies:** Modify RLS policies to use `auth.uid() = user_id`

This will automatically filter all data by the authenticated user!

---

**Current File:** `RLS_FIX_GUIDE.md`
**Related Files:**
- `disable_rls.sql` - SQL script to disable RLS
- `.env` - Contains your Supabase keys
- `SUPABASE_MIGRATION_STATUS.md` - Overall migration status
