#!/usr/bin/env python3
"""
Sync authenticated users from auth.users to public.users table
"""
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def sync_auth_users():
    """Sync all authenticated users to the users table"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Error: SUPABASE_URL and SUPABASE_KEY must be set")
        return False

    print(f"🔗 Connecting to Supabase...")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get all auth users
    try:
        # Use admin API to list users
        response = client.auth.admin.list_users()
        auth_users = response

        if not auth_users:
            print("⚠️  No authenticated users found")
            return True

        print(f"📊 Found {len(auth_users)} authenticated user(s)")

    except Exception as e:
        print(f"❌ Error fetching auth users: {e}")
        return False

    # Sync each user to users table
    synced = 0
    errors = 0

    for user in auth_users:
        try:
            user_id = user.id
            email = user.email

            # Check if user already exists in users table
            result = client.table("users").select("id").eq("id", user_id).execute()

            if result.data:
                print(f"  ⏭️  User already exists: {email}")
                continue

            # Insert into users table
            client.table("users").insert({
                "id": user_id,
                "email": email,
                "username": email.split('@')[0]  # Use email prefix as username
            }).execute()

            synced += 1
            print(f"  ✅ Synced: {email}")

        except Exception as e:
            errors += 1
            print(f"  ❌ Error syncing {email}: {e}")

    print(f"\n{'='*50}")
    print(f"✅ Sync complete!")
    print(f"{'='*50}")
    print(f"  • Users synced: {synced}")
    print(f"  • Already existed: {len(auth_users) - synced - errors}")
    if errors > 0:
        print(f"  • Errors: {errors}")

    return True

if __name__ == "__main__":
    print("="*50)
    print("🔄 Sync Auth Users to Users Table")
    print("="*50)
    print()

    success = sync_auth_users()

    if success:
        print("\n✅ Sync successful!")
    else:
        print("\n❌ Sync failed!")
        exit(1)
