import os
import sqlite3
import datetime as dt
import requests
import streamlit as st
import json
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from supabase import create_client, Client
import auth  # Authentication module
import notifications  # Notifications module
import scheduled_tasks  # Background task scheduler
import preferences  # User notification preferences
import show_status  # Show status tracking from TMDB

# Load environment variables
load_dotenv()

# --------------- CONFIG ---------------
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"
DEFAULT_REGION = os.getenv("TMDB_REGION", "US").upper()
DEFAULT_PROVIDER = "Netflix"
LOGO_OVERRIDES_FILE = "logo_overrides.json"
DELETED_PROVIDERS_FILE = "deleted_providers.json"
USER_SETTINGS_FILE = "user_settings.json"
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "notifications@streamgenie.app").strip()

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Default user ID for single-user mode (fallback if no auth)
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

def get_user_id() -> str:
    """Get the current user ID (authenticated user or default)"""
    user_id = auth.get_user_id()
    return user_id if user_id else DEFAULT_USER_ID

# Popular streaming providers supported by TMDB
STREAMING_PROVIDERS = [
    "Netflix",
    "Amazon Prime Video",
    "Hulu",
    "Disney Plus",
    "Max",
    "Apple TV Plus",
    "Paramount Plus",
    "Peacock",
    "Showtime",
    "Starz",
    "MGM Plus",
    "Crunchyroll",
    "fuboTV",
    "Sling TV",
    "YouTube Premium",
    "Discovery Plus",
    "BritBox",
    "AMC Plus",
    "Shudder",
    "Criterion Channel",
]

DB_PATH = os.getenv("DB_PATH", "shows.db")

# --------------- DB LAYER (Supabase) ---------------
@st.cache_resource
def get_supabase_client() -> Client:
    """Get Supabase client (cached across app reruns)"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("⚠️ Supabase not configured. Please set SUPABASE_URL and SUPABASE_KEY in .env file")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def upsert_show(client: Client, tmdb_id:int, title:str, region:str, on_provider:bool, next_air_date:Optional[str], overview:str, poster_path:Optional[str], provider_name:str):
    """Insert or update a show in the user's watchlist"""
    user_id = get_user_id()

    # Check if show already exists
    existing = client.table("shows")\
        .select("id")\
        .eq("user_id", user_id)\
        .eq("tmdb_id", tmdb_id)\
        .eq("provider_name", provider_name)\
        .execute()

    is_new_show = len(existing.data) == 0

    data = {
        "user_id": user_id,
        "tmdb_id": tmdb_id,
        "title": title,
        "region": region,
        "on_provider": on_provider,
        "next_air_date": next_air_date,
        "overview": overview,
        "poster_path": poster_path,
        "provider_name": provider_name
    }

    # Upsert: insert or update if exists
    client.table("shows").upsert(data, on_conflict="user_id,tmdb_id,provider_name").execute()

    # Create notification for new shows
    if is_new_show:
        status = "available" if on_provider else "unavailable"
        notifications.notify_show_status_change(
            client=client,
            user_id=user_id,
            show_title=title,
            show_id=tmdb_id,
            new_status="added",
            send_email=False
        )

        # Check and update show status from TMDB (series finale/cancellation detection)
        show_status.update_show_status(client, user_id, tmdb_id, title)

def delete_show(client: Client, tmdb_id:int, region:str, provider_name:str):
    """Delete a show from the user's watchlist"""
    client.table("shows")\
        .delete()\
        .eq("user_id", get_user_id())\
        .eq("tmdb_id", tmdb_id)\
        .eq("region", region)\
        .eq("provider_name", provider_name)\
        .execute()

def list_shows(client: Client) -> List[Dict[str, Any]]:
    """Get all shows from the user's watchlist"""
    result = client.table("shows")\
        .select("tmdb_id, title, region, on_provider, provider_name, next_air_date, overview, poster_path, production_status, status_message, status_confidence, in_production")\
        .eq("user_id", get_user_id())\
        .order("title")\
        .execute()
    return result.data

# --------------- TMDB API ---------------
def tmdb_get(path:str, params:Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY is not set. Get one free at themoviedb.org and set the environment variable.")
    headers = {"Authorization": f"Bearer {TMDB_API_KEY}"} if len(TMDB_API_KEY) > 40 else {}
    # Support either v3 key (api_key=) or v4 bearer token
    p = dict(params or {})
    if not headers:
        p["api_key"] = TMDB_API_KEY
    url = f"{TMDB_BASE}{path}"
    r = requests.get(url, params=p, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()

def search_tv(query:str) -> List[Dict[str, Any]]:
    data = tmdb_get("/search/tv", {"query": query, "include_adult": "false", "language": "en-US", "page": 1})
    return data.get("results", [])

def tv_details(tv_id:int) -> Dict[str, Any]:
    return tmdb_get(f"/tv/{tv_id}", {"language": "en-US"})

def tv_watch_providers(tv_id:int) -> Dict[str, Any]:
    return tmdb_get(f"/tv/{tv_id}/watch/providers")

def is_on_provider_in_region(providers_payload:Dict[str, Any], provider_name:str, region:str) -> bool:
    region_block = providers_payload.get("results", {}).get(region.upper())
    if not region_block:
        return False
    # Check any access type (flatrate, buy, rent, ads, free) that contains the provider_name
    for key in ("flatrate", "rent", "buy", "ads", "free"):
        for item in region_block.get(key, []) or []:
            if item.get("provider_name","").lower() == provider_name.lower():
                return True
    return False

def get_all_providers_in_region(providers_payload:Dict[str, Any], region:str) -> Dict[str, List[str]]:
    """Get all available providers for a show in a specific region, organized by access type."""
    region_block = providers_payload.get("results", {}).get(region.upper())
    if not region_block:
        return {}

    providers_by_type = {}
    for access_type in ("flatrate", "rent", "buy", "ads", "free"):
        providers = region_block.get(access_type, []) or []
        if providers:
            providers_by_type[access_type] = [p.get("provider_name", "Unknown") for p in providers]

    return providers_by_type

def discover_next_air_date(details:Dict[str, Any]) -> Optional[str]:
    # Prefer TMDB's next_episode_to_air field if available
    nxt = details.get("next_episode_to_air")
    if isinstance(nxt, dict) and nxt.get("air_date"):
        return nxt["air_date"]
    # Fallback: check upcoming season episodes (rough heuristic)
    # Inspect last and next seasons for any episodes with air_date >= today
    today = dt.date.today()
    for season in details.get("seasons", []) or []:
        season_number = season.get("season_number")
        if season_number is None:
            continue
        try:
            season_full = tmdb_get(f"/tv/{details['id']}/season/{season_number}", {"language":"en-US"})
        except Exception:
            continue
        for ep in (season_full.get("episodes") or []):
            try:
                ad = ep.get("air_date")
                if ad:
                    d = dt.date.fromisoformat(ad)
                    if d >= today:
                        return ad
            except Exception:
                pass
    return None

# --------------- LOGO OVERRIDE PERSISTENCE ---------------
def load_logo_overrides(client: Client) -> dict:
    """Load logo URL overrides from Supabase."""
    try:
        result = client.table("logo_overrides").select("*").execute()
        return {row["provider_name"]: row["logo_url"] for row in result.data}
    except Exception as e:
        st.warning(f"Could not load logo overrides: {e}")
        return {}

def save_logo_overrides(client: Client, overrides: dict):
    """Save logo URL overrides to Supabase."""
    try:
        # Upsert each override (insert or update)
        for provider_name, logo_url in overrides.items():
            client.table("logo_overrides").upsert({
                "provider_name": provider_name,
                "logo_url": logo_url
            }, on_conflict="provider_name").execute()
    except Exception as e:
        st.error(f"Could not save logo overrides: {e}")

def load_deleted_providers(client: Client) -> list:
    """Load list of deleted providers from Supabase."""
    try:
        result = client.table("deleted_providers").select("provider_name").execute()
        return [row["provider_name"] for row in result.data]
    except Exception as e:
        st.warning(f"Could not load deleted providers: {e}")
        return []

def save_deleted_providers(client: Client, deleted: list):
    """Save list of deleted providers to Supabase."""
    try:
        # First, clear all existing deleted providers
        client.table("deleted_providers").delete().neq("provider_name", "").execute()

        # Then insert the new list
        if deleted:
            data = [{"provider_name": provider} for provider in deleted]
            client.table("deleted_providers").insert(data).execute()
    except Exception as e:
        st.error(f"Could not save deleted providers: {e}")

def load_user_settings() -> dict:
    """Load user settings from JSON file."""
    if os.path.exists(USER_SETTINGS_FILE):
        try:
            with open(USER_SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            st.warning(f"Could not load user settings: {e}")
            return {}
    return {}

def save_user_settings(settings: dict):
    """Save user settings to JSON file."""
    try:
        with open(USER_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        st.error(f"Could not save user settings: {e}")

# --------------- UI HELPERS ---------------
def get_all_provider_logos() -> dict:
    """Get all provider logo mappings."""
    provider_logos = {
        # Major Streaming Services
        "netflix": "https://images.justwatch.com/icon/207360008/s100/netflix.webp",
        "amazon prime video": "https://images.justwatch.com/icon/322992749/s100/amazonprime.webp",
        "prime video": "https://images.justwatch.com/icon/322992749/s100/amazonprime.webp",
        "hulu": "https://images.justwatch.com/icon/116305230/s100/hulu.webp",
        "disney plus": "https://images.justwatch.com/icon/313118777/s100/disneyplus.webp",
        "disney+": "https://images.justwatch.com/icon/313118777/s100/disneyplus.webp",
        "max": "https://images.justwatch.com/icon/332884837/s100/max.webp",
        "hbo max": "https://images.justwatch.com/icon/332884837/s100/max.webp",
        "paramount plus": "https://images.justwatch.com/icon/242706661/s100/paramountplus.webp",
        "paramount+": "https://images.justwatch.com/icon/242706661/s100/paramountplus.webp",
        "peacock": "https://images.justwatch.com/icon/194173870/s100/peacocktv.webp",
        "peacock premium": "https://images.justwatch.com/icon/194173870/s100/peacocktv.webp",
        "apple tv plus": "https://images.justwatch.com/icon/338253870/s100/appletvplus.webp",
        "apple tv+": "https://images.justwatch.com/icon/338253870/s100/appletvplus.webp",

        # Premium Channels
        "showtime": "https://images.justwatch.com/icon/430999/s100/showtime.webp",
        "starz": "https://images.justwatch.com/icon/301254735/s100/starz.webp",
        "mgm plus": "https://images.justwatch.com/icon/302467394/s100/epix.webp",
        "amc+": "https://images.justwatch.com/icon/277399832/s100/amcplus.webp",
        "bet+": "https://images.justwatch.com/icon/248153957/s100/bet-plus.webp",
        "espn+": "https://images.justwatch.com/icon/147638348/s100/espn-plus.webp",

        # Specialty Streaming
        "crunchyroll": "https://images.justwatch.com/icon/324213205/s100/crunchyroll.webp",
        "shudder": "https://images.justwatch.com/icon/2562359/s100/shudder.webp",
        "acorn tv": "https://images.justwatch.com/icon/151881328/s100/acorntv.webp",
        "sundance now": "https://images.justwatch.com/icon/5676163/s100/sundancenow.webp",
        "criterion channel": "https://images.justwatch.com/icon/308609719/s100/criterionchannel.webp",

        # Discovery/Learning
        "youtube premium": "https://images.justwatch.com/icon/70189310/s100/youtubered.webp",
        "discovery plus": "https://images.justwatch.com/icon/240558410/s100/discoveryplusus.webp",
        "discovery+": "https://images.justwatch.com/icon/240558410/s100/discoveryplusus.webp",

        # Free Ad-Supported
        "tubi": "https://images.justwatch.com/icon/313528601/s100/tubitv.webp",
        "pluto tv": "https://images.justwatch.com/icon/312204955/s100/plutotv.webp",
        "freevee": "https://images.justwatch.com/icon/300557484/s100/freevee.webp",
        "amazon freevee": "https://images.justwatch.com/icon/300557484/s100/freevee.webp",
        "the roku channel": "https://images.justwatch.com/icon/76972041/s100/rokuchannel.webp",
        "roku channel": "https://images.justwatch.com/icon/76972041/s100/rokuchannel.webp",
        "plex": "https://images.justwatch.com/icon/301832745/s100/plex.webp",
        "xumo play": "https://images.justwatch.com/icon/308802886/s100/xumoplay.webp",

        # Live TV / Cable
        "fubotv": "https://images.justwatch.com/icon/316727345/s100/fubotv.webp",
        "fubo tv": "https://images.justwatch.com/icon/316727345/s100/fubotv.webp",
        "sling tv": "https://images.justwatch.com/icon/430998/s100/sling-tv.webp",
        "directv stream": "https://images.justwatch.com/icon/257197350/s100/directv-stream.webp",
        "spectrum on demand": "https://images.justwatch.com/icon/305635208/s100/spectrumondemand.webp",

        # Rental/Purchase
        "fandango at home": "https://images.justwatch.com/icon/322380782/s100/vudu.webp",
        "vudu": "https://images.justwatch.com/icon/322380782/s100/vudu.webp",
        "amazon video": "https://images.justwatch.com/icon/430993/s100/amazon.webp",
        "apple tv": "https://images.justwatch.com/icon/338253243/s100/itunes.webp",
        "google play movies": "https://images.justwatch.com/icon/169478387/s100/play.webp",
        "google play movies & tv": "https://images.justwatch.com/icon/169478387/s100/play.webp",
        "microsoft store": "https://images.justwatch.com/icon/820542/s100/microsoft-store.webp",
    }

    return provider_logos

def get_provider_logo_url(provider_name: str) -> Optional[str]:
    """Get logo URL for a specific streaming provider."""
    provider_lower = provider_name.lower()

    # Initialize logo_overrides in session state if not present
    if 'logo_overrides' not in st.session_state:
        st.session_state.logo_overrides = load_logo_overrides(client)

    # Check for overrides first (from persistent storage)
    if provider_lower in st.session_state.logo_overrides:
        return st.session_state.logo_overrides[provider_lower]

    provider_logos = get_all_provider_logos()

    # Exact match (preferred)
    if provider_lower in provider_logos:
        return provider_logos[provider_lower]

    # Partial match only for longer, specific keys to avoid false matches
    # Only match if key is at least 4 chars and is a clear substring
    sorted_keys = sorted(provider_logos.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if len(key) >= 4 and key in provider_lower:
            return provider_logos[key]

    return None  # No logo available

def normalize_provider_name(provider_name: str) -> str:
    """Normalize provider names to consolidated versions."""
    provider_lower = provider_name.lower()

    # Consolidate Paramount variations
    if "paramount" in provider_lower:
        return "Paramount+"

    # Consolidate Disney variations
    if "disney" in provider_lower:
        return "Disney+"

    # Consolidate Apple TV variations (but not Apple TV+ the service)
    if "apple tv" in provider_lower and "apple tv+" not in provider_lower:
        # Could be "Apple TV", "Apple TV Channels", etc.
        if "channel" in provider_lower or provider_lower.strip() == "apple tv":
            return "Apple TV+"

    # Consolidate Amazon variations
    if "amazon" in provider_lower or "prime video" in provider_lower:
        return "Prime Video"

    # Consolidate Discovery variations
    if "discovery" in provider_lower:
        return "Discovery+"

    # Consolidate Hulu variations (Hulu, Hulu (No Ads), etc.)
    if "hulu" in provider_lower:
        return "Hulu"

    # Consolidate Fandango variations (and legacy Vudu)
    if "fandango" in provider_lower and "free" not in provider_lower:
        return "Fandango At Home"
    if "vudu" in provider_lower:
        return "Fandango At Home"

    # Consolidate Max variations
    if "hbo" in provider_lower and "max" in provider_lower:
        return "Max"
    if provider_lower.strip() == "max":
        return "Max"

    # Consolidate Google Play variations
    if "google play" in provider_lower:
        return "Google Play Movies"

    # Consolidate Microsoft Store variations
    if "microsoft" in provider_lower:
        return "Microsoft Store"

    # Return original if no consolidation needed
    return provider_name

# --------------- EMAIL REMINDERS ---------------
def send_email_reminder(user_email: str, show_title: str, provider_name: str, next_air_date: str, poster_path: Optional[str] = None):
    """Send an email reminder for a show airing today."""
    if not SENDGRID_API_KEY:
        st.warning("SendGrid API key not configured. Set SENDGRID_API_KEY environment variable.")
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        # Format the email
        poster_img = ""
        if poster_path:
            poster_img = f'<img src="https://image.tmdb.org/t/p/w300{poster_path}" style="max-width: 200px; border-radius: 8px;" />'

        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #E64002;">🎬 {show_title} airs today!</h2>
                {poster_img}
                <p style="font-size: 16px;">
                    <strong>Streaming on:</strong> {provider_name}<br>
                    <strong>Air Date:</strong> {next_air_date}
                </p>
                <p style="color: #666;">
                    Don't miss the latest episode! Check your streaming service now.
                </p>
                <hr style="border: 1px solid #eee; margin: 20px 0;">
                <p style="font-size: 12px; color: #999;">
                    You're receiving this because you're tracking this show in StreamGenie.<br>
                    Manage your watchlist and preferences in the app.
                </p>
            </body>
        </html>
        """

        message = Mail(
            from_email=SENDGRID_FROM_EMAIL,
            to_emails=user_email,
            subject=f'🎬 {show_title} airs today on {provider_name}!',
            html_content=html_content
        )

        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)

        return response.status_code == 202

    except Exception as e:
        st.error(f"Failed to send email: {e}")
        return False

def check_and_send_daily_reminders(user_email: str, client: Client):
    """Check for shows airing today and send email + in-app reminders."""
    if not user_email:
        return 0

    today = dt.date.today().isoformat()
    user_id = get_user_id()

    # Get all shows airing today
    result = client.table("shows")\
        .select("*")\
        .eq("user_id", user_id)\
        .eq("next_air_date", today)\
        .execute()

    shows_today = result.data

    sent_count = 0
    for show in shows_today:
        provider_name = normalize_provider_name(show.get("provider_name", DEFAULT_PROVIDER))

        # Send email reminder
        success = send_email_reminder(
            user_email=user_email,
            show_title=show["title"],
            provider_name=provider_name,
            next_air_date=show["next_air_date"],
            poster_path=show.get("poster_path")
        )

        # Create in-app notification
        notifications.notify_new_episode(
            client=client,
            user_id=user_id,
            show_title=show["title"],
            show_id=show["tmdb_id"],
            air_date=show["next_air_date"],
            send_email=False  # Already sent via send_email_reminder
        )

        if success:
            sent_count += 1

    return sent_count

def format_status(on_provider:bool, next_air_date:Optional[str], provider_name:str) -> str:
    badge = f"✅ On {provider_name}" if on_provider else f"⏳ Not on {provider_name} (in selected region)"
    if next_air_date:
        try:
            d = dt.date.fromisoformat(next_air_date)
            days = (d - dt.date.today()).days
            when = "today" if days == 0 else (f"in {days} days" if days > 0 else f"{abs(days)} days ago")
            return f"{badge} · Next episode: {next_air_date} ({when})"
        except Exception:
            return f"{badge} · Next episode: {next_air_date}"
    return badge

# --------------- STREAMLIT UI ---------------
st.set_page_config(page_title="StreamGenie - Streaming Tracker", page_icon="🍿", layout="wide")

# Initialize Supabase client (needed throughout the app)
client = get_supabase_client()

# Initialize background task scheduler
# This will schedule daily reminders at 8 AM and weekly previews on Sunday at 6 PM
scheduler = scheduled_tasks.init_scheduler(client)

# Initialize authentication
auth.init_auth_session()

# Check if user is authenticated
if not auth.is_authenticated():
    # Show login/signup page
    auth.render_auth_ui(client)
    st.stop()  # Stop execution until user logs in

# User is authenticated - show user menu and continue with app
auth.render_user_menu(client)

# Show notifications in sidebar
notifications.render_notifications_ui(client, get_user_id())

# Header with settings toggle
col_header, col_gear = st.columns([9, 1])
with col_header:
    st.title("🍿 StreamGenie")
    st.caption("Search TV shows, discover streaming availability, and track release dates")
with col_gear:
    st.write("")  # Spacing
    show_settings = st.toggle("⚙️", value=False, help="Show/hide settings")

# Collapsible settings section
if show_settings:
    with st.container(border=True):
        st.markdown("""
        <style>
        [data-testid="stVerticalBlock"] > [style*="flex-direction: column;"] > [data-testid="stVerticalBlock"] {
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
        }
        </style>
        """, unsafe_allow_html=True)
        st.markdown("### ⚙️ Settings")
        col1, col2 = st.columns(2)
        with col1:
            region = st.text_input("Region (ISO-3166-1 code)", value=DEFAULT_REGION, help="e.g., US, CA, GB, AU")
        with col2:
            st.write("")
            st.caption(f"TMDB API: {'✅ Connected' if bool(TMDB_API_KEY) else '❌ Not set'}")
            st.caption(f"Database: {DB_PATH}")

        # Tabs for settings sections
        # Check if user is admin to show Maintenance tab
        user_id = get_user_id()
        user_is_admin = auth.is_admin(client, user_id)

        if user_is_admin:
            tab1, tab2, tab3, tab4 = st.tabs(["ℹ️ How It Works", "🔧 Maintenance", "📧 Email Reminders", "🔔 Notification Preferences"])
        else:
            tab1, tab3, tab4 = st.tabs(["ℹ️ How It Works", "📧 Email Reminders", "🔔 Notification Preferences"])

        with tab1:
            st.caption("1. Search for any TV show")
            st.caption("2. View ALL available streaming services in your region")
            st.caption("3. Select which service(s) to track")
            st.caption("4. Monitor availability and upcoming episode dates")

        with tab3:
            st.markdown("**Email Reminder Settings**")
            st.caption("Get daily email notifications when your tracked shows air")

            # Load current settings
            if 'user_settings' not in st.session_state:
                st.session_state.user_settings = load_user_settings()

            col_email1, col_email2 = st.columns([3, 1])

            with col_email1:
                user_email = st.text_input(
                    "Your Email",
                    value=st.session_state.user_settings.get('email', ''),
                    placeholder="your@email.com",
                    help="Enter your email to receive daily reminders"
                )

            with col_email2:
                st.write("")
                st.write("")
                reminders_enabled = st.checkbox(
                    "Enable",
                    value=st.session_state.user_settings.get('reminders_enabled', False),
                    help="Enable/disable email reminders"
                )

            # Save button
            col_save, col_test, col_spacer = st.columns([1, 1, 2])
            with col_save:
                if st.button("💾 Save Settings", use_container_width=True):
                    st.session_state.user_settings['email'] = user_email
                    st.session_state.user_settings['reminders_enabled'] = reminders_enabled
                    save_user_settings(st.session_state.user_settings)
                    st.success("✅ Settings saved!")

            with col_test:
                if st.button("📧 Test Email", use_container_width=True, disabled=not user_email):
                    if not SENDGRID_API_KEY:
                        st.error("❌ SendGrid API key not configured. Set SENDGRID_API_KEY environment variable.")
                    else:
                        # Send a test email
                        success = send_email_reminder(
                            user_email=user_email,
                            show_title="Test Show",
                            provider_name="Netflix",
                            next_air_date=dt.date.today().isoformat(),
                            poster_path=None
                        )
                        if success:
                            st.success("✅ Test email sent! Check your inbox.")
                        else:
                            st.error("❌ Failed to send test email. Check your configuration.")

            st.write("---")

            # Status display
            st.markdown("**Current Status**")
            st.caption(f"📧 Email: {user_email or 'Not set'}")
            st.caption(f"🔔 Reminders: {'✅ Enabled' if reminders_enabled and user_email else '❌ Disabled'}")
            st.caption(f"🔑 SendGrid API: {'✅ Configured' if SENDGRID_API_KEY else '❌ Not set'}")

            if SENDGRID_API_KEY and reminders_enabled and user_email:
                st.info("📬 You'll receive emails at 8:00 AM when shows air!")
            elif not SENDGRID_API_KEY:
                st.warning("⚠️ To enable reminders, set the SENDGRID_API_KEY environment variable.\n\nGet a free API key at https://sendgrid.com")

        if user_is_admin:
            with tab2:
                st.markdown("**Provider Logo Assignments**")

                # Get all logo assignments
                all_logos = get_all_provider_logos()

                # Initialize session state
                if 'logo_overrides' not in st.session_state:
                    st.session_state.logo_overrides = load_logo_overrides(client)

                if 'deleted_providers' not in st.session_state:
                    st.session_state.deleted_providers = load_deleted_providers(client)

                # Filter out deleted providers
                active_logos = {k: v for k, v in all_logos.items() if k not in st.session_state.deleted_providers}

                override_count = len(st.session_state.logo_overrides)
                deleted_count = len(st.session_state.deleted_providers)

                status_parts = [f"Total providers: {len(active_logos)}"]
                if override_count > 0:
                    status_parts.append(f"**🔧 {override_count} modified**")
                if deleted_count > 0:
                    status_parts.append(f"**🗑️ {deleted_count} deleted**")

                st.caption(" | ".join(status_parts))

                # Group by category
                categories = {
                    "Major Streaming Services": [],
                    "Premium Channels": [],
                    "Specialty Streaming": [],
                    "Discovery/Learning": [],
                    "Free Ad-Supported": [],
                    "Live TV / Cable": [],
                    "Rental/Purchase": []
                }

                # Categorize providers (simple keyword matching)
                for provider in sorted(active_logos.keys()):
                    if provider in ["netflix", "prime video", "amazon prime video", "hulu", "disney plus", "disney+",
                                   "max", "hbo max", "paramount plus", "paramount+", "peacock", "peacock premium",
                                   "apple tv plus", "apple tv+"]:
                        categories["Major Streaming Services"].append(provider)
                    elif provider in ["showtime", "starz", "mgm plus", "amc+", "bet+", "espn+"]:
                        categories["Premium Channels"].append(provider)
                    elif provider in ["crunchyroll", "shudder", "acorn tv", "sundance now", "criterion channel"]:
                        categories["Specialty Streaming"].append(provider)
                    elif provider in ["youtube premium", "discovery plus", "discovery+"]:
                        categories["Discovery/Learning"].append(provider)
                    elif provider in ["tubi", "pluto tv", "freevee", "amazon freevee", "the roku channel", "roku channel", "plex", "xumo play"]:
                        categories["Free Ad-Supported"].append(provider)
                    elif provider in ["fubotv", "fubo tv", "sling tv", "directv stream", "spectrum on demand"]:
                        categories["Live TV / Cable"].append(provider)
                    else:
                        categories["Rental/Purchase"].append(provider)

                # Display by category
                for category, providers in categories.items():
                    if providers:
                        with st.expander(f"**{category}** ({len(providers)} providers)"):
                            for provider in providers:
                                # Add border container for each row
                                with st.container(border=True):
                                    logo_url = get_provider_logo_url(provider)

                                    col1, col2, col3, col4 = st.columns([1, 5, 0.5, 0.5])
                                    with col1:
                                        if logo_url:
                                            st.image(logo_url, width=40)
                                        else:
                                            st.write("❌")

                                    with col2:
                                        # Show if this provider has an override
                                        has_override = 'logo_overrides' in st.session_state and provider in st.session_state.logo_overrides
                                        if has_override:
                                            st.caption(f"**{provider}** 🔧 _(modified)_")
                                        else:
                                            st.caption(f"**{provider}**")

                                        if logo_url:
                                            st.caption(f"`{logo_url}`")
                                        else:
                                            st.caption("_No logo URL assigned_")

                                    with col3:
                                        if st.button("✏️", key=f"edit_{provider}", help=f"Edit {provider} logo URL"):
                                            st.session_state[f"editing_{provider}"] = True
                                            st.rerun()

                                    with col4:
                                        if st.button("🗑️", key=f"delete_{provider}", help=f"Delete {provider} from system"):
                                            # Initialize session state if needed
                                            if 'logo_overrides' not in st.session_state:
                                                st.session_state.logo_overrides = load_logo_overrides(client)
                                            if 'deleted_providers' not in st.session_state:
                                                st.session_state.deleted_providers = load_deleted_providers(client)

                                            # Add to deleted list
                                            if provider not in st.session_state.deleted_providers:
                                                st.session_state.deleted_providers.append(provider)
                                                save_deleted_providers(client, st.session_state.deleted_providers)

                                            # Also remove any override if it exists
                                            if provider in st.session_state.logo_overrides:
                                                del st.session_state.logo_overrides[provider]
                                                save_logo_overrides(client, st.session_state.logo_overrides)

                                            st.toast(f"✅ Deleted {provider}")
                                            st.rerun()

                                # Edit mode
                                if st.session_state.get(f"editing_{provider}", False):
                                    st.markdown(f"**Edit logo URL for: {provider}**")
                                    new_url = st.text_input(
                                        "Logo URL",
                                        value=logo_url or "",
                                        key=f"url_{provider}",
                                        placeholder="https://images.justwatch.com/icon/..."
                                    )

                                    col_save, col_cancel = st.columns(2)
                                    with col_save:
                                        if st.button("💾 Save", key=f"save_{provider}"):
                                            # Initialize logo_overrides if it doesn't exist
                                            if 'logo_overrides' not in st.session_state:
                                                st.session_state.logo_overrides = load_logo_overrides(client)

                                            # Store the new URL in session state and persist to file
                                            st.session_state.logo_overrides[provider] = new_url
                                            save_logo_overrides(client, st.session_state.logo_overrides)

                                            st.session_state[f"editing_{provider}"] = False
                                            st.success(f"✅ Logo URL updated for {provider} and saved to {LOGO_OVERRIDES_FILE}!")
                                            st.rerun()

                                    with col_cancel:
                                        if st.button("❌ Cancel", key=f"cancel_{provider}"):
                                            st.session_state[f"editing_{provider}"] = False
                                            st.rerun()

                                    st.write("---")

                st.write("---")

                # Scheduled Tasks Section with border
                with st.container(border=True):
                    st.markdown("**⏰ Scheduled Tasks**")
                    st.caption("Test automated email reminders and weekly previews")

                    # Show scheduled jobs
                    if scheduler:
                        jobs = scheduler.get_jobs()
                        if jobs:
                            st.info(f"✅ {len(jobs)} scheduled jobs running")
                            for job in jobs:
                                st.caption(f"• {job.name} - Next run: {job.next_run_time.strftime('%Y-%m-%d %I:%M %p') if job.next_run_time else 'N/A'}")
                        else:
                            st.warning("No scheduled jobs found")

                    # Test buttons
                    col_test1, col_test2 = st.columns(2)

                    with col_test1:
                        if st.button("📧 Test Daily Reminders", use_container_width=True, help="Manually trigger daily reminders now"):
                            with st.spinner("Sending daily reminders..."):
                                try:
                                    scheduler.test_daily_reminders_now()
                                    st.success("✅ Daily reminders triggered! Check your email and in-app notifications.")
                                except Exception as e:
                                    st.error(f"❌ Error: {e}")

                    with col_test2:
                        if st.button("📅 Test Weekly Preview", use_container_width=True, help="Manually trigger weekly preview now"):
                            with st.spinner("Sending weekly previews..."):
                                try:
                                    scheduler.test_weekly_preview_now()
                                    st.success("✅ Weekly preview triggered! Check your email and in-app notifications.")
                                except Exception as e:
                                    st.error(f"❌ Error: {e}")

                    st.caption("⏰ Daily reminders run automatically at 8:00 AM EST")
                    st.caption("📅 Weekly previews run automatically on Sundays at 6:00 PM EST")

                st.write("---")

                # Show Status Tracking Section with border
                with st.container(border=True):
                    st.markdown("**📊 Show Status Tracking**")
                    st.caption("Check show status from TMDB (Returning Series, Ended, Canceled)")

                    if st.button("🔍 Check All Show Statuses", use_container_width=True, help="Check TMDB for status updates on all your shows"):
                        with st.spinner("Checking show statuses from TMDB..."):
                            try:
                                user_id = get_user_id()
                                stats = show_status.check_all_shows_status(client, user_id)

                                st.success(f"✅ Status check complete!")
                                st.caption(f"📊 Total shows: {stats['total']}")
                                st.caption(f"🔄 Updated: {stats['updated']}")
                                st.caption(f"✓ Unchanged: {stats['unchanged']}")
                                if stats['errors'] > 0:
                                    st.caption(f"⚠️ Errors: {stats['errors']}")

                                if stats['updated'] > 0:
                                    st.info("📬 Check your notifications for any status changes!")
                            except Exception as e:
                                st.error(f"❌ Error: {e}")

                    st.caption("💡 Show statuses are automatically checked when you add a show to your watchlist")

                st.write("---")

                # User Management Section with border
                with st.container(border=True):
                    st.markdown("**👥 User Management**")
                    st.caption("Manage user roles and permissions")

                    # Get current admin user ID
                    admin_user_id = get_user_id()

                    # Get all users
                    all_users = auth.list_all_users(client)

                    if not all_users:
                        st.info("No users found in the system")
                    else:
                        # Count by role
                        admin_count = sum(1 for u in all_users if u.get('user_role') == 'admin')
                        user_count = sum(1 for u in all_users if u.get('user_role') == 'user')

                        st.caption(f"📊 Total users: {len(all_users)} | 👑 Admins: {admin_count} | 👤 Users: {user_count}")

                        st.write("")

                        # Display users in a table-like format
                        for user in all_users:
                            user_id = user.get('id')
                            email = user.get('email', 'Unknown')
                            role = user.get('user_role', 'user')
                            is_current_user = (user_id == admin_user_id)

                            with st.container(border=True):
                                col1, col2, col3 = st.columns([3, 1, 1])

                                with col1:
                                    # Show email and role
                                    role_emoji = "👑" if role == "admin" else "👤"
                                    current_badge = " **(You)**" if is_current_user else ""
                                    st.markdown(f"{role_emoji} **{email}**{current_badge}")
                                    st.caption(f"Role: {role.capitalize()}")

                                with col2:
                                    # Promote button (only for regular users)
                                    if role == "user":
                                        if st.button("⬆️ Make Admin", key=f"promote_{user_id}", use_container_width=True):
                                            success, message = auth.promote_to_admin(client, user_id, admin_user_id)
                                            if success:
                                                st.success(message)
                                                st.rerun()
                                            else:
                                                st.error(message)

                                with col3:
                                    # Demote button (only for admins, not yourself)
                                    if role == "admin" and not is_current_user:
                                        if st.button("⬇️ Remove Admin", key=f"demote_{user_id}", use_container_width=True):
                                            success, message = auth.demote_to_user(client, user_id, admin_user_id)
                                            if success:
                                                st.success(message)
                                                st.rerun()
                                            else:
                                                st.error(message)
                                    elif is_current_user and role == "admin":
                                        st.caption("_(Cannot demote yourself)_")

                        st.write("")
                        st.info("💡 **Tip:** At least one admin must exist at all times. You cannot demote yourself or the last remaining admin.")

        with tab4:
            st.markdown("**🔔 Customize Your Notifications**")
            st.caption("Choose which notifications you want to receive via email and in-app")

            # Get user preferences
            user_id = get_user_id()
            user_prefs = preferences.get_or_create_preferences(client, user_id)

            st.write("")
            st.markdown("### 📧 Email Notifications")
            st.caption("Control which types of email notifications you receive")

            col_email1, col_email2 = st.columns(2)

            with col_email1:
                email_new_episodes = st.checkbox(
                    "🎬 New Episodes Airing",
                    value=user_prefs.get("email_new_episodes", True),
                    help="Get an email when a tracked show has a new episode airing today",
                    key="pref_email_new_episodes"
                )

                email_series_finale = st.checkbox(
                    "🎭 Series Finales",
                    value=user_prefs.get("email_series_finale", True),
                    help="Get notified when a tracked show's final episode airs",
                    key="pref_email_series_finale"
                )

                email_show_added = st.checkbox(
                    "➕ Show Added to Watchlist",
                    value=user_prefs.get("email_show_added", False),
                    help="Get an email when you add a new show to your watchlist",
                    key="pref_email_show_added"
                )

            with col_email2:
                email_weekly_preview = st.checkbox(
                    "📅 Weekly Preview",
                    value=user_prefs.get("email_weekly_preview", True),
                    help="Get a weekly email on Sunday with all shows airing in the next 7 days",
                    key="pref_email_weekly_preview"
                )

                email_series_cancelled = st.checkbox(
                    "❌ Show Cancellations",
                    value=user_prefs.get("email_series_cancelled", True),
                    help="Get notified when a tracked show is cancelled",
                    key="pref_email_series_cancelled"
                )

            st.write("---")
            st.markdown("### 📱 In-App Notifications")
            st.caption("Control which notifications appear in the sidebar")

            col_inapp1, col_inapp2 = st.columns(2)

            with col_inapp1:
                inapp_new_episodes = st.checkbox(
                    "🎬 New Episodes Airing",
                    value=user_prefs.get("inapp_new_episodes", True),
                    help="Show in-app notifications for new episodes",
                    key="pref_inapp_new_episodes"
                )

                inapp_series_finale = st.checkbox(
                    "🎭 Series Finales",
                    value=user_prefs.get("inapp_series_finale", True),
                    help="Show in-app notifications for series finales",
                    key="pref_inapp_series_finale"
                )

                inapp_show_added = st.checkbox(
                    "➕ Show Added to Watchlist",
                    value=user_prefs.get("inapp_show_added", True),
                    help="Show in-app notifications when adding shows",
                    key="pref_inapp_show_added"
                )

            with col_inapp2:
                inapp_weekly_preview = st.checkbox(
                    "📅 Weekly Preview",
                    value=user_prefs.get("inapp_weekly_preview", True),
                    help="Show in-app notifications for weekly previews",
                    key="pref_inapp_weekly_preview"
                )

                inapp_series_cancelled = st.checkbox(
                    "❌ Show Cancellations",
                    value=user_prefs.get("inapp_series_cancelled", True),
                    help="Show in-app notifications for cancelled shows",
                    key="pref_inapp_series_cancelled"
                )

            st.write("---")

            # Save button
            col_save_prefs, col_spacer = st.columns([1, 3])
            with col_save_prefs:
                if st.button("💾 Save Preferences", use_container_width=True):
                    # Collect all preferences
                    updates = {
                        "email_new_episodes": email_new_episodes,
                        "email_weekly_preview": email_weekly_preview,
                        "email_series_finale": email_series_finale,
                        "email_series_cancelled": email_series_cancelled,
                        "email_show_added": email_show_added,
                        "inapp_new_episodes": inapp_new_episodes,
                        "inapp_weekly_preview": inapp_weekly_preview,
                        "inapp_series_finale": inapp_series_finale,
                        "inapp_series_cancelled": inapp_series_cancelled,
                        "inapp_show_added": inapp_show_added
                    }

                    # Update preferences
                    if preferences.update_preferences(client, user_id, updates):
                        st.success("✅ Notification preferences saved!")
                        st.balloons()
                    else:
                        st.error("❌ Failed to save preferences. Please try again.")

            st.write("")
            st.info("💡 **Tip:** All notifications will appear in the sidebar notification center. You can control which types trigger emails separately.")

        st.write("---")
else:
    region = DEFAULT_REGION

# Note: Background scheduler initialized at top of file via scheduled_tasks.init_scheduler()

# Vertical layout: Search on top, watchlist below
st.subheader("🔎 Search TV Shows")
st.caption(f"Searching in region: **{region}** — Shows availability for all streaming services")

# Use session state to track when to clear search
if 'clear_search' not in st.session_state:
    st.session_state.clear_search = False

# Clear the search if flag is set
if st.session_state.clear_search:
    st.session_state.clear_search = False
    st.rerun()

q = st.text_input("Search for a TV show", "", placeholder="Wednesday, Stranger Things, Squid Game...", key="search_input")
if q:
    try:
        results = search_tv(q)
    except Exception as e:
        st.error(f"TMDB error: {e}")
        results = []

    if not results:
        st.info("No results. Try a different title.")
    else:
        for r in results[:20]:
            # Add padding above each result
            st.markdown("<div style='padding-top: 10px;'></div>", unsafe_allow_html=True)

            cols = st.columns([1, 3, 6])
            poster_path = r.get("poster_path")
            title = r.get("name") or r.get("original_name") or "Untitled"
            tmdb_id = r.get("id")
            overview = (r.get("overview") or "").strip()
            img_url = f"https://image.tmdb.org/t/p/w200{poster_path}" if poster_path else None

            with cols[0]:
                if img_url:
                    st.image(img_url, use_column_width=True)

            with cols[1]:
                st.markdown(f"**{title}**")
                st.caption(f"TMDB ID: {tmdb_id}")

            with cols[2]:
                st.write((overview[:280] + "…") if len(overview) > 280 else overview or "_No synopsis available._")

                # Show all available providers
                with st.expander("📺 View Streaming Availability & Add to Watchlist", expanded=False):
                    try:
                        det = tv_details(tmdb_id)
                        prov = tv_watch_providers(tmdb_id)
                        next_air = discover_next_air_date(det)

                        # Get all providers in the region
                        all_providers = get_all_providers_in_region(prov, region)

                        # Show next air date at the top
                        if next_air:
                            try:
                                d = dt.date.fromisoformat(next_air)
                                days = (d - dt.date.today()).days
                                when = "today" if days == 0 else (f"in {days} days" if days > 0 else f"{abs(days)} days ago")
                                st.info(f"📅 Next episode: {next_air} ({when})")
                            except Exception:
                                st.info(f"📅 Next episode: {next_air}")

                        # Collect all unique provider names and normalize them
                        available_provider_names = []
                        for providers_list in all_providers.values():
                            for provider in providers_list:
                                normalized = normalize_provider_name(provider)
                                if normalized not in available_provider_names:
                                    available_provider_names.append(normalized)
                        available_provider_names = sorted(available_provider_names)

                        if available_provider_names:
                            st.caption("💡 Click any logo to add to watchlist")

                            # Create logo grid (4 per row for better spacing)
                            for i in range(0, len(available_provider_names), 4):
                                cols = st.columns(4)
                                for j, col in enumerate(cols):
                                    if i + j < len(available_provider_names):
                                        provider = available_provider_names[i + j]
                                        normalized_provider = normalize_provider_name(provider)
                                        with col:
                                            logo_url = get_provider_logo_url(normalized_provider)

                                            # Create clickable logo/button
                                            if logo_url:
                                                # Show logo with click handler
                                                st.image(logo_url, width=80)
                                                # Use "Add" button below logo
                                                clicked = st.button("Add", key=f"add_{tmdb_id}_{provider.replace(' ', '_')}", use_container_width=True)
                                            else:
                                                # Show provider name text and button when logo not available
                                                st.write(f"**{normalized_provider}**")
                                                clicked = st.button("Add", key=f"add_{tmdb_id}_{provider.replace(' ', '_')}", use_container_width=True)

                                            if clicked:
                                                try:
                                                    on_provider = is_on_provider_in_region(prov, provider, region)
                                                    upsert_show(client, tmdb_id, title, region, on_provider, next_air, overview, poster_path, normalized_provider)
                                                    st.success(f"✅ Added '{title}' to watchlist for {normalized_provider}!")
                                                    st.session_state.clear_search = True
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Failed: {e}")
                        else:
                            # If no providers available, might be broadcast TV
                            if next_air:
                                # Has air date but no streaming = likely broadcast TV
                                st.info(f"📺 This show airs on broadcast/cable TV")
                                st.caption("Add it to track upcoming episodes:")

                                # Add Broadcast TV option
                                if st.button("➕ 📺 Broadcast/Cable TV", key=f"add_broadcast_{tmdb_id}", use_container_width=True):
                                    try:
                                        upsert_show(client, tmdb_id, title, region, True, next_air, overview, poster_path, "Broadcast TV")
                                        st.success(f"✅ Added '{title}' to watchlist!")
                                        st.session_state.clear_search = True
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Failed: {e}")

                                st.write("---")
                                st.caption("Or track it for when it comes to streaming:")
                            else:
                                st.warning(f"⚠️ Not available in {region}")
                                st.caption("You can still track it for future availability:")

                            # Show top streaming services as logo buttons
                            top_services = ["Netflix", "Prime Video", "Hulu", "Disney+", "Max", "Paramount+"]

                            for i in range(0, len(top_services), 4):
                                cols = st.columns(4)
                                for j, col in enumerate(cols):
                                    if i + j < len(top_services):
                                        provider = top_services[i + j]
                                        with col:
                                            logo_url = get_provider_logo_url(provider)

                                            # Create clickable logo/button
                                            if logo_url:
                                                st.image(logo_url, width=80)
                                                clicked = st.button("Add", key=f"add_manual_{tmdb_id}_{provider.replace(' ', '_')}", use_container_width=True)
                                            else:
                                                st.write(f"**{provider}**")
                                                clicked = st.button("Add", key=f"add_manual_{tmdb_id}_{provider.replace(' ', '_')}", use_container_width=True)

                                            if clicked:
                                                try:
                                                    upsert_show(client, tmdb_id, title, region, False, next_air, overview, poster_path, provider)
                                                    st.success(f"✅ Added '{title}' to watchlist for {provider}!")
                                                    st.session_state.clear_search = True
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Failed: {e}")

                    except Exception as e:
                        st.error(f"Lookup error: {e}")

            # Add padding below each result
            st.markdown("<div style='padding-bottom: 10px;'></div>", unsafe_allow_html=True)

# Watchlist section below search
st.write("---")

# Header with icon actions
header_cols = st.columns([9, 1])
with header_cols[0]:
    st.subheader("📺 Your Watchlist")
with header_cols[1]:
    export_csv = st.button("⬇️", key="export_icon", help="Export to CSV")

rows = list_shows(client)

# Auto-update production status for shows that don't have it
if rows:
    user_id = get_user_id()
    for row in rows:
        # Check if production_status is missing or null
        if not row.get('production_status'):
            try:
                # Silently update status in background
                show_status.update_show_status(client, user_id, row['tmdb_id'], row['title'])
            except Exception:
                pass  # Silently fail, don't interrupt display
    # Refresh rows after updates
    rows = list_shows(client)

if not rows:
    st.info("Your watchlist is empty. Search and add shows from above.")
else:

    if export_csv:
        import csv, io
        df = []
        for r in rows:
            provider_name = r.get("provider_name", DEFAULT_PROVIDER)
            df.append({
                "Title": r["title"],
                "Region": r["region"],
                "Provider": provider_name,
                "Available?": "Yes" if r["on_provider"] else "No",
                "Next Air Date": r["next_air_date"] or "",
                "Status": format_status(bool(r["on_provider"]), r["next_air_date"], provider_name),
            })
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(df[0].keys()))
        writer.writeheader()
        writer.writerows(df)
        st.download_button("📥 Download watchlist.csv", buf.getvalue(), file_name="watchlist.csv", mime="text/csv", use_container_width=True)

    st.write("---")

    # Sort controls
    sort_cols = st.columns([2, 2, 2, 6])
    with sort_cols[0]:
        if st.button("📝 Title ↕️", key="sort_title", use_container_width=True, help="Sort by title"):
            if "sort_by" not in st.session_state or st.session_state.sort_by != "title":
                st.session_state.sort_by = "title"
                st.session_state.sort_order = "asc"
            else:
                st.session_state.sort_order = "desc" if st.session_state.sort_order == "asc" else "asc"
            st.rerun()

    with sort_cols[1]:
        if st.button("📺 Service ↕️", key="sort_service", use_container_width=True, help="Sort by streaming service"):
            if "sort_by" not in st.session_state or st.session_state.sort_by != "service":
                st.session_state.sort_by = "service"
                st.session_state.sort_order = "asc"
            else:
                st.session_state.sort_order = "desc" if st.session_state.sort_order == "asc" else "asc"
            st.rerun()

    with sort_cols[2]:
        if st.button("📅 Date ↕️", key="sort_date", use_container_width=True, help="Sort by next air date"):
            if "sort_by" not in st.session_state or st.session_state.sort_by != "date":
                st.session_state.sort_by = "date"
                st.session_state.sort_order = "asc"
            else:
                st.session_state.sort_order = "desc" if st.session_state.sort_order == "asc" else "asc"
            st.rerun()

    # Apply sorting
    sort_by = st.session_state.get("sort_by", "title")
    sort_order = st.session_state.get("sort_order", "asc")

    if sort_by == "title":
        rows = sorted(rows, key=lambda x: x["title"].lower(), reverse=(sort_order == "desc"))
    elif sort_by == "date":
        # Sort by date - None values (no air date) go last when ascending, first when descending
        def date_sort_key(r):
            date = r.get("next_air_date")
            if not date:
                return "9999-99-99" if sort_order == "asc" else "0000-00-00"
            return date
        rows = sorted(rows, key=date_sort_key, reverse=(sort_order == "desc"))
    elif sort_by == "service":
        rows = sorted(rows, key=lambda x: normalize_provider_name(x.get("provider_name", "")).lower(), reverse=(sort_order == "desc"))

    st.caption(f"Tracking {len(rows)} show(s) • Sorted by {sort_by} ({sort_order})")

    for r in rows:
        provider_name = r.get("provider_name", DEFAULT_PROVIDER)
        # Normalize the provider name for display
        display_provider_name = normalize_provider_name(provider_name)
        next_air_date = r.get("next_air_date")

        # Single row layout: Image | Info | Date | Actions
        cols = st.columns([1, 4, 3, 2])

        # Column 1: Poster image
        with cols[0]:
            poster_path = r.get("poster_path")
            if poster_path:
                img_url = f"https://image.tmdb.org/t/p/w92{poster_path}"
                st.image(img_url, use_column_width=True)
            else:
                st.write("🎬")

        # Column 2: Title and provider info with logo
        with cols[1]:
            # Create a row with logo and title
            title_cols = st.columns([1, 10])
            with title_cols[0]:
                logo_url = get_provider_logo_url(display_provider_name)
                if logo_url:
                    st.image(logo_url, width=48)  # Doubled from 24 to 48
            with title_cols[1]:
                st.markdown(f"**{r['title']}**")

            status_icon = "✅" if r['on_provider'] else "⏳"
            st.caption(f"{status_icon} {display_provider_name} • {r['region']}")

        # Column 3: Next air date with countdown
        with cols[2]:
            if next_air_date:
                try:
                    air_date = dt.date.fromisoformat(next_air_date)
                    days = (air_date - dt.date.today()).days

                    if days == 0:
                        st.markdown("🔴 **TODAY**")
                    elif days > 0:
                        st.markdown(f"📅 **{next_air_date}**")
                        st.caption(f"⏰ in {days} day{'s' if days != 1 else ''}")
                    else:
                        st.markdown(f"📅 {next_air_date}")
                        st.caption(f"({abs(days)} day{'s' if abs(days) != 1 else ''} ago)")
                except Exception:
                    st.caption(f"📅 {next_air_date}")
            else:
                # Show enhanced production status if available
                production_status = r.get('production_status')
                status_message = r.get('status_message')

                if production_status:
                    # Display enhanced production intelligence
                    st.markdown(f"**{production_status}**")
                    if status_message:
                        st.caption(status_message)
                elif r['on_provider']:
                    # Fallback to old display for shows without enhanced status
                    st.markdown("✨ **All Episodes**")
                    st.caption("Series complete")
                else:
                    st.caption("❓ No air date")
                    st.caption("↓ Check status")

        # Column 4: Action buttons (avoid nested columns)
        with cols[3]:
            # Show only delete button - status updates happen automatically
            if st.button("🗑️", key=f"del_{r['tmdb_id']}_{provider_name}", help="Remove", use_container_width=True):
                delete_show(client, r["tmdb_id"], r["region"], provider_name)
                st.rerun()

        st.divider()