# 👥 User Management - Admin Guide

## ✅ Overview

StreamGenie now includes a **User Management interface** that allows admins to promote or demote users directly from the web UI - no SQL queries needed!

---

## 🎯 Features

- ✅ **View all users** - See every registered user with their role
- ✅ **Promote to admin** - Make any regular user an admin with one click
- ✅ **Demote to user** - Remove admin privileges from users
- ✅ **Safety protections:**
  - Cannot demote yourself
  - Cannot demote the last admin
  - Only admins can manage users
- ✅ **User statistics** - See total users, admin count, regular user count
- ✅ **Visual indicators** - Crown emoji for admins, user emoji for regular users

---

## 📍 Where to Find It

1. **Login** as an admin at https://streamgenie-estero.streamlit.app
2. Click **⚙️ Settings** toggle (bottom left)
3. Click **🔧 Maintenance** tab
4. Scroll down to **👥 User Management** section

---

## 🖼️ What You'll See

```
👥 User Management
Manage user roles and permissions

📊 Total users: 3 | 👑 Admins: 1 | 👤 Users: 2

┌──────────────────────────────────────────┐
│ 👑 jjwoods@gmail.com (You)               │
│ Role: Admin                              │
│                        (Cannot demote yourself) │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ 👤 user1@example.com                     │
│ Role: User                               │
│                    [⬆️ Make Admin]       │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ 👑 admin2@example.com                    │
│ Role: Admin                              │
│                 [⬇️ Remove Admin]        │
└──────────────────────────────────────────┘

💡 Tip: At least one admin must exist at all times.
```

---

## 🔧 How to Use

### Promote a User to Admin

1. Find the user in the list (they'll have 👤 emoji)
2. Click **"⬆️ Make Admin"** button
3. ✅ Success message appears
4. User immediately becomes admin
5. They'll see the Maintenance tab next time they refresh

### Demote an Admin to Regular User

1. Find the admin in the list (they'll have 👑 emoji)
2. Click **"⬇️ Remove Admin"** button
3. ✅ Success message appears
4. User loses admin privileges immediately
5. Maintenance tab disappears for them

---

## 🔒 Safety Features

### Cannot Demote Yourself
**Why:** Prevents accidental lockout
**What happens:** Button replaced with _(Cannot demote yourself)_ message

### Cannot Demote Last Admin
**Why:** System must always have at least one admin
**What happens:** Error message: *"Cannot demote the last admin. Promote another user first."*

**Solution:** Promote another user to admin first, then demote the original admin.

### Only Admins Can Manage Users
**Why:** Security - regular users shouldn't change roles
**What happens:** Regular users don't see this section at all

---

## 📋 Common Tasks

### Make Someone an Admin

**Scenario:** New team member joins and needs admin access

**Steps:**
1. Ask them to create an account at https://streamgenie-estero.streamlit.app
2. Ask them for their email address
3. Open Settings > Maintenance > User Management
4. Find their email in the list
5. Click "⬆️ Make Admin"
6. ✅ Done! They can refresh to see Maintenance tab

### Remove Admin Access

**Scenario:** Team member leaving or no longer needs admin access

**Steps:**
1. Open Settings > Maintenance > User Management
2. Find their email in the list
3. Click "⬇️ Remove Admin"
4. ✅ Done! They lose admin access immediately

### Transfer Admin Rights

**Scenario:** You want to step down as admin and make someone else the primary admin

**Steps:**
1. First, promote the new admin (see above)
2. Verify they can access Maintenance tab
3. Have them demote you (they need to do it, you can't demote yourself)
4. ✅ Done! Primary admin changed

### Check All Admins

**Look at the statistics line:**
```
📊 Total users: 10 | 👑 Admins: 2 | 👤 Users: 8
```

**Or scroll through the list** - admins have 👑 crown emoji

---

## 🚨 Troubleshooting

### "Cannot demote the last admin"

**Problem:** Trying to remove the only admin

**Solution:**
1. Promote another user to admin first
2. Then demote the original admin

### User Not in List

**Problem:** New user signed up but not showing

**Cause:** They may have only authenticated but not created a user record

**Solution:**
1. Ask them to add at least one show to their watchlist
2. Refresh the User Management page
3. They should appear now

### Changes Not Taking Effect

**Problem:** Promoted user but they don't see Maintenance tab

**Solution:**
1. Ask them to hard refresh browser (Cmd+Shift+R / Ctrl+Shift+F5)
2. Or clear browser cache
3. Or try incognito/private browsing mode

---

## 🎯 Best Practices

### Limit Number of Admins
- **Recommended:** 1-3 admins for small teams
- **Why:** Too many admins = security risk
- **Who should be admin:**
  - System owners
  - Technical leads
  - Support team leads

### Audit Regularly
- Check User Management section monthly
- Remove admin access from inactive users
- Verify all admins still need access

### Document Your Admins
Keep a record of who has admin access:
```
Admin Users:
- jjwoods@gmail.com (Primary admin, system owner)
- admin2@example.com (Technical lead)
- support@company.com (Support lead)
```

### Communication
When promoting/demoting:
- ✅ **Do:** Notify the user before changing their role
- ✅ **Do:** Explain why they're getting/losing admin access
- ❌ **Don't:** Remove admin access without warning

---

## 🔍 Behind the Scenes

### What Happens When You Promote a User?

1. **Click "Make Admin"** button
2. System calls `auth.promote_to_admin(client, user_id, admin_user_id)`
3. Function checks:
   - You are an admin ✓
   - Target user exists ✓
4. Updates database: `users.user_role = 'admin'`
5. Success message shown
6. Page refreshes
7. User's next page load includes Maintenance tab

### What Happens When You Demote an Admin?

1. **Click "Remove Admin"** button
2. System calls `auth.demote_to_user(client, user_id, admin_user_id)`
3. Function checks:
   - You are an admin ✓
   - Not trying to demote yourself ✓
   - Not the last admin ✓
4. Updates database: `users.user_role = 'user'`
5. Success message shown
6. Page refreshes
7. User's next page load hides Maintenance tab

### Database Changes

```sql
-- Before promotion
user_role = 'user'

-- After promotion
user_role = 'admin'

-- After demotion
user_role = 'user'
```

---

## 📊 Alternative Methods

While the UI is recommended, you can still manage users via SQL if needed:

### Check All Users and Roles
```sql
SELECT email, user_role, created_at
FROM users
ORDER BY created_at DESC;
```

### Promote User via SQL
```sql
UPDATE users
SET user_role = 'admin'
WHERE email = 'user@example.com';
```

### Demote User via SQL
```sql
UPDATE users
SET user_role = 'user'
WHERE email = 'admin@example.com';
```

### Count by Role
```sql
SELECT user_role, COUNT(*) as count
FROM users
GROUP BY user_role;
```

---

## 🎓 Training New Admins

### Checklist for New Admins

Share this with newly promoted admins:

**What You Can Now Do:**
- ✅ Manage provider logos
- ✅ Manually trigger scheduled tasks (daily reminders, weekly previews)
- ✅ Check show statuses for all users
- ✅ Promote/demote other users

**What You Should Know:**
- ⚠️ **Provider Logos:** Changes affect all users
- ⚠️ **Scheduled Tasks:** Use sparingly, they send emails to all users
- ⚠️ **User Management:** Can't demote yourself
- ⚠️ **Last Admin:** System prevents demoting the last admin

**Where to Learn More:**
- Read `ADMIN_ROLE_SETUP.md` for role system overview
- Read `USER_MANAGEMENT.md` (this file) for user management

---

## 🔮 Future Enhancements

Potential features for future versions:

### Near-Term
- **Search/Filter** - Find users by email quickly
- **Bulk Actions** - Promote/demote multiple users at once
- **Last Login** - See when users last accessed the app

### Medium-Term
- **Audit Log** - Track who promoted/demoted whom and when
- **Role History** - See role changes over time
- **Email Notifications** - Notify users when their role changes

### Long-Term
- **Custom Roles** - Moderator, Support, Premium, etc.
- **Permissions Matrix** - Fine-grained control over features
- **Team Management** - Group users into teams

---

## 💡 Tips & Tricks

### Quick Admin Check
Want to know if you're an admin?
- Open Settings
- If you see "🔧 Maintenance" tab → You're an admin ✅
- If you only see 3 tabs → You're a regular user

### Emergency Admin Access
Lost all admins? Use Supabase SQL Editor:
```sql
UPDATE users
SET user_role = 'admin'
WHERE email = 'your-email@example.com';
```

### Temporary Admin Access
Need to give someone temporary admin access?
1. Promote them
2. Set calendar reminder to demote them later
3. When reminder fires, demote them

---

## 📞 Support

### Questions?

**"Can I have multiple admins?"**
✅ Yes! Promote as many users as you need.

**"Can I demote myself?"**
❌ No, for safety reasons. Another admin must demote you.

**"What if I accidentally demote everyone?"**
✅ System prevents demoting the last admin.

**"Do promoted users need to log out/in?"**
❌ No, just refresh the page.

**"Can regular users see who the admins are?"**
❌ No, User Management is admin-only.

---

**Status:** ✅ Ready to Use

**Created:** 2025-11-03

**Related Files:**
- `auth.py` - User management functions (lines 343-444)
- `app.py` - User management UI (lines 883-946)
- `ADMIN_ROLE_SETUP.md` - Role system overview
