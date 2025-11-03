#!/usr/bin/env python3
"""
Migration script to move data from SQLite to Supabase PostgreSQL
"""
import sqlite3
import json
import os
from supabase import create_client, Client
from datetime import datetime

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SQLITE_DB = os.getenv("DB_PATH", "shows.db")

# Default user ID for single-user data migration
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

def migrate_data():
    """Migrate all data from SQLite to Supabase"""

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Error: SUPABASE_URL and SUPABASE_KEY must be set in .env file")
        return False

    if not os.path.exists(SQLITE_DB):
        print(f"❌ Error: SQLite database not found at {SQLITE_DB}")
        return False

    # Connect to Supabase
    print(f"🔗 Connecting to Supabase at {SUPABASE_URL}...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Connect to SQLite
    print(f"📂 Reading from SQLite database: {SQLITE_DB}")
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row
    cursor = sqlite_conn.cursor()

    # Count existing rows
    cursor.execute("SELECT COUNT(*) FROM shows")
    total_shows = cursor.fetchone()[0]
    print(f"📊 Found {total_shows} shows in SQLite database")

    if total_shows == 0:
        print("⚠️  No shows to migrate")
        return True

    # Migrate shows
    print("\n📺 Migrating shows...")
    cursor.execute("SELECT * FROM shows")
    shows = cursor.fetchall()

    migrated = 0
    errors = 0

    for show in shows:
        try:
            # Convert SQLite row to dict
            show_data = {
                "user_id": DEFAULT_USER_ID,
                "tmdb_id": show["tmdb_id"],
                "title": show["title"],
                "region": show["region"],
                "on_provider": bool(show["on_provider"]),
                "next_air_date": show["next_air_date"] if show["next_air_date"] else None,
                "overview": show["overview"] if show["overview"] else None,
                "poster_path": show["poster_path"] if show["poster_path"] else None,
                "provider_name": show["provider_name"] if show["provider_name"] else "Netflix"
            }

            # Insert into Supabase
            result = supabase.table("shows").insert(show_data).execute()

            if result.data:
                migrated += 1
                print(f"  ✅ Migrated: {show['title']}")
            else:
                errors += 1
                print(f"  ❌ Failed: {show['title']}")

        except Exception as e:
            errors += 1
            print(f"  ❌ Error migrating {show['title'] if 'title' in show.keys() else 'Unknown'}: {e}")

    print(f"\n✅ Shows migrated: {migrated}/{total_shows}")
    if errors > 0:
        print(f"⚠️  Errors: {errors}")

    # Migrate logo overrides from JSON file
    logo_overrides_file = "logo_overrides.json"
    if os.path.exists(logo_overrides_file):
        print(f"\n🎨 Migrating logo overrides from {logo_overrides_file}...")
        with open(logo_overrides_file, 'r') as f:
            logo_overrides = json.load(f)

        for provider, logo_url in logo_overrides.items():
            try:
                result = supabase.table("logo_overrides").upsert({
                    "provider_name": provider,
                    "logo_url": logo_url
                }).execute()
                print(f"  ✅ Migrated logo override: {provider}")
            except Exception as e:
                print(f"  ❌ Error migrating logo override for {provider}: {e}")

    # Migrate deleted providers from JSON file
    deleted_providers_file = "deleted_providers.json"
    if os.path.exists(deleted_providers_file):
        print(f"\n🗑️  Migrating deleted providers from {deleted_providers_file}...")
        with open(deleted_providers_file, 'r') as f:
            deleted_providers = json.load(f)

        for provider in deleted_providers:
            try:
                result = supabase.table("deleted_providers").upsert({
                    "provider_name": provider
                }).execute()
                print(f"  ✅ Migrated deleted provider: {provider}")
            except Exception as e:
                print(f"  ❌ Error migrating deleted provider {provider}: {e}")

    # Migrate user settings from JSON file
    user_settings_file = "user_settings.json"
    if os.path.exists(user_settings_file):
        print(f"\n⚙️  Migrating user settings from {user_settings_file}...")
        with open(user_settings_file, 'r') as f:
            settings = json.load(f)

        try:
            result = supabase.table("user_settings").upsert({
                "user_id": DEFAULT_USER_ID,
                "email_notifications": settings.get("reminders_enabled", False),
                "reminder_time": "08:00:00",
                "timezone": "America/New_York"
            }).execute()
            print(f"  ✅ Migrated user settings")
        except Exception as e:
            print(f"  ❌ Error migrating user settings: {e}")

    sqlite_conn.close()

    print("\n" + "="*50)
    print("✅ Migration complete!")
    print("="*50)
    print(f"\n📊 Summary:")
    print(f"  • Shows migrated: {migrated}")
    print(f"  • Logo overrides: {len(logo_overrides) if os.path.exists(logo_overrides_file) else 0}")
    print(f"  • Deleted providers: {len(deleted_providers) if os.path.exists(deleted_providers_file) else 0}")
    print(f"\n🔍 Next steps:")
    print(f"  1. Verify data in Supabase dashboard: {SUPABASE_URL}")
    print(f"  2. Update app.py to use Supabase")
    print(f"  3. Test the application")

    return True

if __name__ == "__main__":
    print("="*50)
    print("🚀 StreamGenie SQLite → Supabase Migration")
    print("="*50)
    print()

    success = migrate_data()

    if success:
        print("\n✅ Migration successful!")
    else:
        print("\n❌ Migration failed!")
        exit(1)
