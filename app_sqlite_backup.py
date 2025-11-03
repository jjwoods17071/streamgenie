import os
import sqlite3
import datetime as dt
import requests
import streamlit as st
import json
from typing import Optional, Dict, Any, List

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

# --------------- DB LAYER ---------------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    # Check if we need to migrate from old schema
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shows'")
    table_exists = cursor.fetchone() is not None

    if table_exists:
        # Check current schema
        cursor = conn.execute("PRAGMA table_info(shows)")
        columns = {row[1] for row in cursor.fetchall()}

        if 'on_netflix' in columns and 'on_provider' not in columns:
            # Migration needed: recreate table with new schema
            conn.execute("ALTER TABLE shows RENAME TO shows_old")
            conn.execute("""
                CREATE TABLE shows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tmdb_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    region TEXT NOT NULL,
                    on_provider INTEGER NOT NULL DEFAULT 0,
                    provider_name TEXT NOT NULL DEFAULT 'Netflix',
                    next_air_date TEXT,
                    last_checked TEXT NOT NULL,
                    overview TEXT,
                    poster_path TEXT
                )
            """)
            conn.execute("""
                INSERT INTO shows (id, tmdb_id, title, region, on_provider, provider_name, next_air_date, last_checked, overview, poster_path)
                SELECT id, tmdb_id, title, region, on_netflix, 'Netflix', next_air_date, last_checked, overview, poster_path
                FROM shows_old
            """)
            conn.execute("DROP TABLE shows_old")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_show ON shows(tmdb_id, region, provider_name)")
            conn.commit()
        elif 'on_provider' in columns:
            # Already migrated, just ensure index exists
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_show ON shows(tmdb_id, region, provider_name)")
    else:
        # New database, create with current schema
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tmdb_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                region TEXT NOT NULL,
                on_provider INTEGER NOT NULL DEFAULT 0,
                provider_name TEXT NOT NULL DEFAULT 'Netflix',
                next_air_date TEXT,
                last_checked TEXT NOT NULL,
                overview TEXT,
                poster_path TEXT
            )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_show ON shows(tmdb_id, region, provider_name)")

    return conn

def upsert_show(conn, tmdb_id:int, title:str, region:str, on_provider:bool, next_air_date:Optional[str], overview:str, poster_path:Optional[str], provider_name:str):
    now = dt.datetime.now(dt.UTC).isoformat()
    conn.execute("""
        INSERT INTO shows (tmdb_id, title, region, on_provider, provider_name, next_air_date, last_checked, overview, poster_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tmdb_id, region, provider_name) DO UPDATE SET
            title=excluded.title,
            on_provider=excluded.on_provider,
            next_air_date=excluded.next_air_date,
            last_checked=excluded.last_checked,
            overview=excluded.overview,
            poster_path=excluded.poster_path
    """, (tmdb_id, title, region, 1 if on_provider else 0, provider_name, next_air_date, now, overview, poster_path))
    conn.commit()

def delete_show(conn, tmdb_id:int, region:str, provider_name:str):
    conn.execute("DELETE FROM shows WHERE tmdb_id=? AND region=? AND provider_name=?", (tmdb_id, region, provider_name))
    conn.commit()

def list_shows(conn) -> List[Dict[str, Any]]:
    cur = conn.execute("SELECT tmdb_id, title, region, on_provider, provider_name, next_air_date, last_checked, overview, poster_path FROM shows ORDER BY title")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

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
def load_logo_overrides() -> dict:
    """Load logo URL overrides from JSON file."""
    if os.path.exists(LOGO_OVERRIDES_FILE):
        try:
            with open(LOGO_OVERRIDES_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            st.warning(f"Could not load logo overrides: {e}")
            return {}
    return {}

def save_logo_overrides(overrides: dict):
    """Save logo URL overrides to JSON file."""
    try:
        with open(LOGO_OVERRIDES_FILE, 'w') as f:
            json.dump(overrides, f, indent=2)
    except Exception as e:
        st.error(f"Could not save logo overrides: {e}")

def load_deleted_providers() -> list:
    """Load list of deleted providers from JSON file."""
    if os.path.exists(DELETED_PROVIDERS_FILE):
        try:
            with open(DELETED_PROVIDERS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            st.warning(f"Could not load deleted providers: {e}")
            return []
    return []

def save_deleted_providers(deleted: list):
    """Save list of deleted providers to JSON file."""
    try:
        with open(DELETED_PROVIDERS_FILE, 'w') as f:
            json.dump(deleted, f, indent=2)
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
        st.session_state.logo_overrides = load_logo_overrides()

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

def check_and_send_daily_reminders(user_email: str, conn):
    """Check for shows airing today and send email reminders."""
    if not user_email:
        return 0

    today = dt.date.today().isoformat()

    # Get all shows airing today
    shows_today = conn.execute(
        "SELECT * FROM shows WHERE next_air_date = ?", (today,)
    ).fetchall()

    sent_count = 0
    for show in shows_today:
        provider_name = normalize_provider_name(show.get("provider_name", DEFAULT_PROVIDER))
        success = send_email_reminder(
            user_email=user_email,
            show_title=show["title"],
            provider_name=provider_name,
            next_air_date=show["next_air_date"],
            poster_path=show.get("poster_path")
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
    with st.container():
        st.markdown("### ⚙️ Settings")
        col1, col2 = st.columns(2)
        with col1:
            region = st.text_input("Region (ISO-3166-1 code)", value=DEFAULT_REGION, help="e.g., US, CA, GB, AU")
        with col2:
            st.write("")
            st.caption(f"TMDB API: {'✅ Connected' if bool(TMDB_API_KEY) else '❌ Not set'}")
            st.caption(f"Database: {DB_PATH}")

        # Tabs for settings sections
        tab1, tab2, tab3 = st.tabs(["ℹ️ How It Works", "🔧 Maintenance", "📧 Email Reminders"])

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

        with tab2:
            st.markdown("**Provider Logo Assignments**")

            # Get all logo assignments
            all_logos = get_all_provider_logos()

            # Initialize session state
            if 'logo_overrides' not in st.session_state:
                st.session_state.logo_overrides = load_logo_overrides()

            if 'deleted_providers' not in st.session_state:
                st.session_state.deleted_providers = load_deleted_providers()

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
                                            st.session_state.logo_overrides = load_logo_overrides()
                                        if 'deleted_providers' not in st.session_state:
                                            st.session_state.deleted_providers = load_deleted_providers()

                                        # Add to deleted list
                                        if provider not in st.session_state.deleted_providers:
                                            st.session_state.deleted_providers.append(provider)
                                            save_deleted_providers(st.session_state.deleted_providers)

                                        # Also remove any override if it exists
                                        if provider in st.session_state.logo_overrides:
                                            del st.session_state.logo_overrides[provider]
                                            save_logo_overrides(st.session_state.logo_overrides)

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
                                            st.session_state.logo_overrides = load_logo_overrides()

                                        # Store the new URL in session state and persist to file
                                        st.session_state.logo_overrides[provider] = new_url
                                        save_logo_overrides(st.session_state.logo_overrides)

                                        st.session_state[f"editing_{provider}"] = False
                                        st.success(f"✅ Logo URL updated for {provider} and saved to {LOGO_OVERRIDES_FILE}!")
                                        st.rerun()

                                with col_cancel:
                                    if st.button("❌ Cancel", key=f"cancel_{provider}"):
                                        st.session_state[f"editing_{provider}"] = False
                                        st.rerun()

                                st.write("---")

        st.write("---")
else:
    region = DEFAULT_REGION

conn = get_conn()

# --------------- BACKGROUND SCHEDULER FOR REMINDERS ---------------
# Initialize scheduler for daily reminder checks
if 'scheduler_started' not in st.session_state:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        def scheduled_reminder_check():
            """Run daily at 8 AM to check for shows airing today."""
            settings = load_user_settings()
            user_email = settings.get('email', '')
            if user_email and settings.get('reminders_enabled', False):
                conn_bg = get_conn()
                sent_count = check_and_send_daily_reminders(user_email, conn_bg)
                conn_bg.close()
                print(f"Daily reminder check: {sent_count} emails sent")

        scheduler = BackgroundScheduler()
        scheduler.add_job(scheduled_reminder_check, 'cron', hour=8, minute=0)
        scheduler.start()
        st.session_state.scheduler_started = True
    except Exception as e:
        print(f"Could not start scheduler: {e}")

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
                                                    upsert_show(conn, tmdb_id, title, region, on_provider, next_air, overview, poster_path, normalized_provider)
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
                                        upsert_show(conn, tmdb_id, title, region, True, next_air, overview, poster_path, "Broadcast TV")
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
                                                    upsert_show(conn, tmdb_id, title, region, False, next_air, overview, poster_path, provider)
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
header_cols = st.columns([8, 1, 1])
with header_cols[0]:
    st.subheader("📺 Your Watchlist")
with header_cols[1]:
    do_refresh = st.button("🔄", key="refresh_icon", help="Refresh all shows")
with header_cols[2]:
    export_csv = st.button("⬇️", key="export_icon", help="Export to CSV")

rows = list_shows(conn)
if not rows:
    st.info("Your watchlist is empty. Search and add shows from above.")
else:

    if do_refresh:
        with st.spinner("Refreshing all shows..."):
            for row in rows:
                try:
                    det = tv_details(row["tmdb_id"])
                    prov = tv_watch_providers(row["tmdb_id"])
                    provider_name = row.get("provider_name", DEFAULT_PROVIDER)
                    on_nf = is_on_provider_in_region(prov, provider_name, row["region"])
                    next_air = discover_next_air_date(det)
                    upsert_show(conn, row["tmdb_id"], det.get("name") or row["title"], row["region"], on_nf, next_air, det.get("overview") or row["overview"], det.get("poster_path") or row["poster_path"], provider_name)
                except Exception as e:
                    st.warning(f"Refresh failed for {row['title']}: {e}")
            rows = list_shows(conn)
        st.success("✅ Refreshed!")
        st.rerun()

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
                # Show is available but no upcoming episodes
                if r['on_provider']:
                    st.markdown("✨ **All Episodes**")
                    st.caption("Series complete")
                else:
                    st.caption("❓ No air date")
                    st.caption("↓ Check status")

        # Column 4: Action buttons (avoid nested columns)
        with cols[3]:
            if next_air_date:
                # Show only refresh and delete for shows with air dates
                if st.button("🔄", key=f"refresh_{r['tmdb_id']}_{provider_name}", help="Refresh", use_container_width=True):
                    try:
                        det = tv_details(r["tmdb_id"])
                        prov = tv_watch_providers(r["tmdb_id"])
                        on_nf = is_on_provider_in_region(prov, provider_name, r["region"])
                        next_air = discover_next_air_date(det)
                        upsert_show(conn, r["tmdb_id"], det.get("name") or r["title"], r["region"], on_nf, next_air, det.get("overview") or r["overview"], det.get("poster_path") or r["poster_path"], provider_name)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
                if st.button("🗑️", key=f"del_{r['tmdb_id']}_{provider_name}", help="Remove", use_container_width=True):
                    delete_show(conn, r["tmdb_id"], r["region"], provider_name)
                    st.rerun()
            else:
                # Show Info toggle, refresh, and delete for shows without air dates
                # Use session state to track which info panels are open
                info_key = f"show_info_{r['tmdb_id']}_{provider_name}"
                if info_key not in st.session_state:
                    st.session_state[info_key] = False

                if st.button("🔍 Info", key=f"info_btn_{r['tmdb_id']}_{provider_name}", help="Check if show is renewed, cancelled, or complete", use_container_width=True):
                    st.session_state[info_key] = not st.session_state[info_key]
                    st.rerun()

                # Show info if toggled on
                if st.session_state[info_key]:
                    st.info(f"💡 **About '{r['title']}':**")

                    if r['on_provider']:
                        st.success("✅ This show is available to stream!")
                        st.caption("No upcoming episodes means this is likely:")
                        st.caption("• A completed series (all episodes available)")
                        st.caption("• Between seasons (check for renewal news)")
                    else:
                        st.warning("⏳ Not currently available in your region")
                        st.caption("No air date may indicate:")
                        st.caption("• Show has been cancelled")
                        st.caption("• Series has concluded")
                        st.caption("• Not yet announced for your region")

                    st.markdown(f"🔍 [Search Google for renewal status ↗](https://www.google.com/search?q={r['title'].replace(' ', '+')}+renewed+cancelled+status)")

                if st.button("🔄", key=f"refresh_{r['tmdb_id']}_{provider_name}", help="Refresh", use_container_width=True):
                    try:
                        det = tv_details(r["tmdb_id"])
                        prov = tv_watch_providers(r["tmdb_id"])
                        on_nf = is_on_provider_in_region(prov, provider_name, r["region"])
                        next_air = discover_next_air_date(det)
                        upsert_show(conn, r["tmdb_id"], det.get("name") or r["title"], r["region"], on_nf, next_air, det.get("overview") or r["overview"], det.get("poster_path") or r["poster_path"], provider_name)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
                if st.button("🗑️", key=f"del_{r['tmdb_id']}_{provider_name}", help="Remove", use_container_width=True):
                    delete_show(conn, r["tmdb_id"], r["region"], provider_name)
                    st.rerun()

        st.divider()