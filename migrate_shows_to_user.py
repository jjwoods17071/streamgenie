#!/usr/bin/env python3
"""
Migrate shows from DEFAULT_USER_ID to a specific authenticated user
"""
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

def migrate_shows_to_user(target_email: str):
    """
    Migrate all shows from DEFAULT_USER_ID to the specified user's account
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Error: SUPABASE_URL and SUPABASE_KEY must be set")
        return False

    print(f"🔗 Connecting to Supabase...")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get the target user's ID by email
    try:
        # Query users table to find user by email
        result = client.table("users").select("id").eq("email", target_email).execute()

        if not result.data:
            print(f"❌ Error: No user found with email {target_email}")
            print("   Make sure you've created an account first!")
            return False

        target_user_id = result.data[0]["id"]
        print(f"✅ Found user: {target_email}")
        print(f"   User ID: {target_user_id}")

    except Exception as e:
        print(f"❌ Error finding user: {e}")
        return False

    # Get all shows from default user
    try:
        result = client.table("shows").select("*").eq("user_id", DEFAULT_USER_ID).execute()
        shows = result.data

        if not shows:
            print("⚠️  No shows found to migrate")
            return True

        print(f"\n📊 Found {len(shows)} shows to migrate")

    except Exception as e:
        print(f"❌ Error fetching shows: {e}")
        return False

    # Migrate each show
    migrated = 0
    errors = 0

    for show in shows:
        try:
            # Delete the old show
            client.table("shows")\
                .delete()\
                .eq("user_id", DEFAULT_USER_ID)\
                .eq("tmdb_id", show["tmdb_id"])\
                .eq("provider_name", show["provider_name"])\
                .execute()

            # Insert with new user_id
            new_show = show.copy()
            new_show["user_id"] = target_user_id
            del new_show["id"]  # Remove the ID to let Supabase generate a new one

            client.table("shows").insert(new_show).execute()

            migrated += 1
            print(f"  ✅ Migrated: {show['title']} ({show['provider_name']})")

        except Exception as e:
            errors += 1
            print(f"  ❌ Error migrating {show['title']}: {e}")

    print(f"\n{'='*50}")
    print(f"✅ Migration complete!")
    print(f"{'='*50}")
    print(f"  • Shows migrated: {migrated}/{len(shows)}")
    if errors > 0:
        print(f"  • Errors: {errors}")

    print(f"\n🎉 All your shows are now in your account!")
    print(f"   You can now log in as {target_email} and see them.")

    return True

if __name__ == "__main__":
    print("="*50)
    print("🔄 StreamGenie Show Migration")
    print("="*50)
    print()

    email = input("Enter your email address: ").strip()

    if not email:
        print("❌ Email is required")
        exit(1)

    print()
    success = migrate_shows_to_user(email)

    if success:
        print("\n✅ Migration successful!")
    else:
        print("\n❌ Migration failed!")
        exit(1)
