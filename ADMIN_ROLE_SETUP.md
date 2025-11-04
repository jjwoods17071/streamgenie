# 🔐 Admin Role-Based Access Control - Setup Guide

## ✅ What's Been Implemented

StreamGenie now has a **user role system** that restricts administrative functions to admin users only!

### Features:
- ✅ User role column in database ('user', 'admin')
- ✅ Role checking functions in auth.py
- ✅ Maintenance tab hidden from regular users
- ✅ Only admins can access:
  - Provider logo assignments
  - Scheduled task testing (daily reminders, weekly previews)
  - Show status checking button
- ✅ Regular users still have access to:
  - Search and watchlist
  - Email reminder settings
  - Notification preferences
  - In-app notifications

---

## 🚀 Deployment Steps

### Step 1: Run SQL Migration in Supabase

1. Open your Supabase dashboard: https://supabase.com/dashboard/project/cmmdkvsxvkhbbusfowgr/sql
2. Click **"New Query"**
3. Copy the entire contents of `add_user_roles.sql`
4. **⚠️ IMPORTANT:** Update line 27 with YOUR email address:
   ```sql
   UPDATE users
   SET user_role = 'admin'
   WHERE email = 'jjwoods@gmail.com';  -- CHANGE THIS TO YOUR EMAIL!
   ```
5. Click **"Run"**
6. ✅ You should see a success message confirming admin user(s) were set

---

### Step 2: Push Code to GitHub

```bash
cd /Users/jjwoods/StreamGenie

# Check what's changed
git status

# Add all new/modified files
git add add_user_roles.sql auth.py app.py ADMIN_ROLE_SETUP.md

# Commit
git commit -m "Add admin role-based access control for Maintenance tab"

# Push to GitHub
git push origin main
```

---

### Step 3: Wait for Auto-Deploy

Streamlit Cloud will automatically deploy within 1-2 minutes after you push.

---

### Step 4: Test Role-Based Access

#### Test as Admin (You):
1. Go to https://streamgenie-estero.streamlit.app
2. Login with your account (jjwoods@gmail.com)
3. Click **⚙️ Settings** toggle
4. You should see **4 tabs**:
   - ℹ️ How It Works
   - **🔧 Maintenance** (Admin only!)
   - 📧 Email Reminders
   - 🔔 Notification Preferences
5. Click **Maintenance** tab
6. You should see all admin functions:
   - Provider Logo Assignments
   - Scheduled Tasks (Test Daily Reminders, Test Weekly Preview)
   - Show Status Tracking

#### Test as Regular User:
1. Create a test account with a different email
2. Login with test account
3. Click **⚙️ Settings** toggle
4. You should see **only 3 tabs** (no Maintenance tab):
   - ℹ️ How It Works
   - 📧 Email Reminders
   - 🔔 Notification Preferences
5. ✅ Regular user cannot access admin functions

---

## 📊 Database Schema

### users Table - New Column

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `user_role` | TEXT | 'user' | User's role ('user', 'admin') |

**Constraint:** `CHECK (user_role IN ('user', 'admin'))`

**Index:** `idx_users_role` for fast role lookups

---

## 🔧 Files Created/Modified

### New Files:

1. **`add_user_roles.sql`** (~40 lines)
   - Adds `user_role` column to `users` table
   - Creates constraint to only allow 'user' or 'admin'
   - Creates index for performance
   - Sets your email as admin
   - Includes verification

### Modified Files:

2. **`auth.py`** (+140 lines)
   - Added role-based access control functions:
     - `get_user_role(client, user_id)` - Get user's role
     - `is_admin(client, user_id)` - Check if user is admin
     - `require_admin(client, user_id)` - Raise error if not admin
     - `set_user_role(client, user_id, role)` - Change user's role
     - `get_user_email_by_id(client, user_id)` - Get email by user ID
     - `list_admins(client)` - Get all admin users

3. **`app.py`** (lines 594-882)
   - Added `user_is_admin = auth.is_admin(client, user_id)` check
   - Conditional tabs creation:
     - Admins: 4 tabs (including Maintenance)
     - Regular users: 3 tabs (no Maintenance)
   - Wrapped entire Maintenance tab content in `if user_is_admin:` block

---

## 🎯 How It Works

### When User Opens Settings

```python
# app.py lines 594-601
user_id = get_user_id()
user_is_admin = auth.is_admin(client, user_id)

if user_is_admin:
    tab1, tab2, tab3, tab4 = st.tabs(["ℹ️ How It Works", "🔧 Maintenance", "📧 Email Reminders", "🔔 Notification Preferences"])
else:
    tab1, tab3, tab4 = st.tabs(["ℹ️ How It Works", "📧 Email Reminders", "🔔 Notification Preferences"])
```

### Role Checking Function

```python
# auth.py lines 199-224
def get_user_role(client: Client, user_id: str) -> str:
    """Get the role for a user"""
    result = client.table("users").select("user_role").eq("id", user_id).execute()

    if result.data and len(result.data) > 0:
        return result.data[0].get("user_role", "user")

    return "user"  # Fail safely to regular user

def is_admin(client: Client, user_id: str) -> bool:
    """Check if user is an admin"""
    role = get_user_role(client, user_id)
    return role == "admin"
```

---

## 🔒 Security Considerations

### ✅ What's Secure:
- **Database-backed roles** - Cannot be faked in browser
- **Fail-safe defaults** - If role check fails, user is treated as regular user
- **RLS policies** - Users can only access their own data
- **No URL-based access** - Admin features aren't at a separate URL that could be discovered

### ⚠️ What to Watch:
- **Only set admin role for trusted users** - They can trigger scheduled tasks manually
- **Admin can modify provider logos** - Could affect all users
- **Admin can test email sending** - Uses SendGrid quota

---

## 🎨 User Experience

### Admin User:
- Sees all 4 tabs in Settings
- Can manage provider logos
- Can manually trigger scheduled tasks
- Can check show statuses
- Full access to all features

### Regular User:
- Sees 3 tabs in Settings (no Maintenance)
- Can customize notification preferences
- Can set up email reminders
- Can use search and watchlist
- Cannot access admin functions

---

## 🔮 Future Enhancements (Optional)

### Near-Term:
- **Moderator Role** - Between user and admin (can manage logos but not tasks)
- **Admin Dashboard** - Dedicated page showing all users, stats, system health
- **Audit Log** - Track which admin performed which actions

### Medium-Term:
- **User Management UI** - Admins can promote/demote users through UI
- **Role Permissions Matrix** - Fine-grained control over specific features
- **Multi-Admin Support** - Team of admins with different permissions

### Long-Term:
- **Organization Support** - Multiple organizations with their own admins
- **SAML/SSO** - Enterprise authentication
- **Advanced RBAC** - Custom roles with granular permissions

---

## 🧪 Testing Checklist

### Initial Setup
- [ ] Run `add_user_roles.sql` in Supabase
- [ ] Verify your email is set as admin in SQL
- [ ] Push code to GitHub
- [ ] Wait for Streamlit Cloud auto-deploy

### Test Admin Access
- [ ] Login with admin account (your email)
- [ ] See 4 tabs in Settings
- [ ] Can access Maintenance tab
- [ ] Can see Provider Logo Assignments
- [ ] Can see Scheduled Tasks section
- [ ] Can see Show Status Tracking section
- [ ] Can click "Test Daily Reminders" button
- [ ] Can click "Test Weekly Preview" button
- [ ] Can click "Check All Show Statuses" button

### Test Regular User Access
- [ ] Create test account with different email
- [ ] Login with test account
- [ ] See only 3 tabs in Settings
- [ ] No Maintenance tab visible
- [ ] Can still use all other features
- [ ] Can set notification preferences
- [ ] Can configure email reminders

---

## 🐛 Troubleshooting

### Admin Can't See Maintenance Tab

**Symptom:** Logged in with admin email but still only see 3 tabs

**Possible Causes:**
1. SQL migration didn't run successfully
2. Email in SQL doesn't match login email
3. Database hasn't updated yet

**Fix:**
```sql
-- Check your current role in Supabase SQL Editor
SELECT id, email, user_role FROM users WHERE email = 'jjwoods@gmail.com';

-- If user_role is NULL or 'user', update it:
UPDATE users SET user_role = 'admin' WHERE email = 'jjwoods@gmail.com';
```

---

### Regular User Can See Maintenance Tab

**Symptom:** Test user can see Maintenance tab

**Cause:** Code not deployed or browser cache

**Fix:**
1. Check Streamlit Cloud deployment completed
2. Hard refresh browser (Cmd+Shift+R / Ctrl+Shift+F5)
3. Clear browser cache
4. Try incognito/private browsing mode

---

### "AttributeError: module 'auth' has no attribute 'is_admin'"

**Symptom:** Error when opening Settings

**Cause:** auth.py not imported or old version cached

**Fix:**
1. Verify auth.py has the new functions (lines 199-340)
2. Check Streamlit Cloud logs for import errors
3. Restart Streamlit app

---

### Can't Set Other Users as Admin

**Current Limitation:** There's no UI to promote other users to admin yet

**Workaround:** Use Supabase SQL Editor:
```sql
-- Get user ID first
SELECT id, email, user_role FROM users WHERE email = 'other-user@example.com';

-- Set as admin
UPDATE users SET user_role = 'admin' WHERE email = 'other-user@example.com';

-- Verify
SELECT id, email, user_role FROM users WHERE user_role = 'admin';
```

---

## 📈 Success Metrics

### Immediate Benefits:
- ✅ Maintenance functions restricted to admins
- ✅ Regular users have cleaner UI (no unnecessary tabs)
- ✅ Foundation for future role-based features
- ✅ Professional security model

### Track These Metrics:
- **Admin Count:** How many admins do you have?
- **Manual Task Triggers:** How often do admins manually trigger tasks?
- **Logo Modifications:** How often are provider logos updated?
- **Support Tickets:** Did regular users try to access admin features?

---

## 🎯 Key Benefits

### For Admins:
- ✅ Full control over system configuration
- ✅ Can manually trigger scheduled tasks
- ✅ Can manage provider logos
- ✅ Can check show statuses for all users

### For Regular Users:
- ✅ Cleaner, simpler interface
- ✅ No confusing admin options
- ✅ Faster page load (less UI to render)
- ✅ Still have full notification control

### For Development:
- ✅ Scalable role system
- ✅ Easy to add more roles
- ✅ Secure database-backed approach
- ✅ No URL-based security (more secure)

---

## 📞 Next Steps

1. **Deploy Now:**
   - Update email in add_user_roles.sql
   - Run SQL migration in Supabase
   - Push code to GitHub
   - Test in production

2. **Soon:**
   - Add more admins if needed (via SQL)
   - Monitor admin activity
   - Collect feedback from users

3. **Later:**
   - Build admin dashboard
   - Add audit logging
   - Implement user management UI

---

**Status:** ✅ Code Complete, Ready to Deploy

**Created:** 2025-11-03

**Files:**
- `add_user_roles.sql` - Database migration
- `auth.py` - Role checking functions
- `app.py` - Conditional Maintenance tab
- `ADMIN_ROLE_SETUP.md` - This file

---

## 🔑 SQL Quick Reference

### Check Your Role
```sql
SELECT email, user_role FROM users WHERE email = 'your-email@example.com';
```

### Set Someone as Admin
```sql
UPDATE users SET user_role = 'admin' WHERE email = 'their-email@example.com';
```

### List All Admins
```sql
SELECT id, email, user_role, created_at FROM users WHERE user_role = 'admin';
```

### Demote Admin to Regular User
```sql
UPDATE users SET user_role = 'user' WHERE email = 'their-email@example.com';
```

### Count Users by Role
```sql
SELECT user_role, COUNT(*) as count FROM users GROUP BY user_role;
```
