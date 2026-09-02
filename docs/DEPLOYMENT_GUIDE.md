# 🚀 StreamGenie Deployment Guide

Your code is now on GitHub! Let's deploy to Streamlit Cloud.

## ✅ Prerequisites (Already Done!)
- ✅ Code pushed to GitHub: https://github.com/jjwoods17071/streamgenie
- ✅ requirements.txt created
- ✅ .gitignore configured (secrets protected)

---

## 🌐 Deploy to Streamlit Cloud (FREE)

### Step 1: Sign Up / Log In to Streamlit Cloud

1. Go to: https://share.streamlit.io
2. Click **"Sign up"** or **"Sign in"**
3. Choose **"Continue with GitHub"**
4. Authorize Streamlit to access your GitHub account

### Step 2: Deploy Your App

1. Once logged in, click **"New app"** (top right)
2. Fill in the deployment form:

   **Repository**: `jjwoods17071/streamgenie`

   **Branch**: `main`

   **Main file path**: `app.py`

   **App URL** (optional): Choose a custom subdomain like `streamgenie` or leave default

3. Click **"Advanced settings"** (IMPORTANT!)

### Step 3: Configure Secrets

In the Advanced settings, you'll see a **"Secrets"** section. This is where you'll add your environment variables.

**Copy and paste this** into the secrets box (replace with your actual values):

```toml
# TMDB API Key
TMDB_API_KEY = "98e894f9b6ee5fe7439016b9226fb588"
TMDB_REGION = "US"

# Supabase Configuration
SUPABASE_URL = "https://cmmdkvsxvkhbbusfowgr.supabase.co"
SUPABASE_KEY = "<YOUR_SERVICE_ROLE_KEY>   # never commit a real key"

# SendGrid Configuration (for email notifications)
SENDGRID_API_KEY = "YOUR_SENDGRID_API_KEY"
SENDGRID_FROM_EMAIL = "joe@outdoorkitchenstore.com"
```

**IMPORTANT**: Replace `YOUR_SENDGRID_API_KEY` with your actual SendGrid API key if you have one, or remove these lines if you don't want email notifications yet.

### Step 4: Deploy!

1. Click **"Deploy!"** (bottom right)
2. Wait 2-3 minutes while Streamlit builds and deploys your app
3. You'll see logs scrolling - this is normal!
4. When done, you'll see: **"Your app is live!"** 🎉

### Step 5: Test Your Deployed App

1. Your app will be live at: `https://[your-app-name].streamlit.app`
2. Try these tests:
   - ✅ Login/Signup works
   - ✅ Search for a TV show
   - ✅ Add to watchlist
   - ✅ Check notifications in sidebar
   - ✅ Logout and login again

---

## 🔧 Troubleshooting

### App Won't Start?

**Check the logs** in Streamlit Cloud:
1. Go to your app dashboard
2. Click "Manage app" → "Logs"
3. Look for error messages

**Common issues**:

#### Missing Secrets
Error: `KeyError: 'SUPABASE_URL'`
- Solution: Add all secrets in Advanced settings → Secrets

#### Wrong Requirements
Error: `ModuleNotFoundError: No module named 'supabase'`
- Solution: Make sure requirements.txt is in the repo root

#### Authentication Issues
Error: `new row violates row-level security`
- Solution: Make sure you're using the service_role key in secrets, not anon key

### App Deployed But Features Don't Work?

#### Email Notifications Not Working
- Normal! You need to add SENDGRID_API_KEY to secrets
- Or remove email functionality for now

#### Can't Add Shows
- Check Supabase secrets are correct
- Make sure notifications table is created (run SQL script)

#### Login Issues
- Verify Supabase Auth is enabled
- Check email confirmation is disabled in Supabase

---

## 🎨 Customization

### Change App URL

After deployment:
1. Go to Streamlit Cloud dashboard
2. Click your app → "Settings"
3. Change "App URL"
4. Save (may take a few minutes to update)

### Update App

Just push to GitHub:
```bash
git add .
git commit -m "Update feature"
git push
```

Streamlit Cloud will **auto-deploy** within 1-2 minutes!

---

## 🔐 Security Best Practices

### ✅ Done Automatically:
- `.env` file excluded via `.gitignore`
- Secrets stored in Streamlit Cloud (encrypted)
- Service role key kept private

### 🚨 Never Do This:
- ❌ Don't commit `.env` file
- ❌ Don't hardcode API keys in code
- ❌ Don't share service_role key publicly

### 🔒 Optional Enhancements:
- Enable GitHub branch protection
- Add `.streamlit/secrets.toml` to `.gitignore` (already done)
- Rotate API keys regularly

---

## 📊 Monitoring Your App

### View Analytics

1. Go to Streamlit Cloud dashboard
2. Click your app
3. See:
   - **Viewers**: How many people are using your app
   - **Resource usage**: CPU, memory
   - **Logs**: Real-time logs

### Check Logs

```
Streamlit Cloud Dashboard → Your App → Logs
```

Useful for debugging production issues!

---

## 🚀 What's Next After Deployment?

### Immediate:
1. ✅ Test all features on live app
2. 📧 Share URL with family/friends
3. 📱 Add to phone home screen (it's mobile-friendly!)

### Soon:
1. 🔔 Test notifications system (run SQL script first)
2. 📅 Set up weekly preview emails
3. 🎨 Customize branding/colors
4. 📊 Add analytics/tracking

### Future:
1. 🌐 Custom domain (e.g., streamgenie.com)
2. 📱 Native mobile app
3. 💎 Premium features
4. 👥 Social features

---

## 💰 Pricing

**Streamlit Community Cloud**: FREE
- Unlimited public apps
- 1 private app
- 1 GB RAM
- Perfect for StreamGenie!

**If you need more**:
- Streamlit Cloud Teams: $250/month (5 private apps)
- Or deploy to your own server (Railway, Render, AWS, etc.)

---

## 🎉 You Did It!

StreamGenie is now:
- ✅ Version controlled on GitHub
- ✅ Deployed to the cloud
- ✅ Accessible from anywhere
- ✅ Automatically updating on push
- ✅ Secure with encrypted secrets
- ✅ Ready to share!

**Your app URL**: `https://[your-app-name].streamlit.app`

Share it with friends and family! 🍿

---

## 📞 Need Help?

- **Streamlit Docs**: https://docs.streamlit.io/streamlit-community-cloud
- **Community Forum**: https://discuss.streamlit.io
- **GitHub Issues**: https://github.com/jjwoods17071/streamgenie/issues

---

**Created**: 2025-11-03
**Status**: Ready to deploy! 🚀
