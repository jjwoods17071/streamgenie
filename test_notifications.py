#!/usr/bin/env python3
"""
Test script to create sample notifications
"""
import os
from supabase import create_client
from dotenv import load_dotenv
import notifications

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def test_notifications():
    """Create sample notifications for testing"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Error: SUPABASE_URL and SUPABASE_KEY must be set")
        return False

    print(f"🔗 Connecting to Supabase...")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get your user ID
    print("\n📧 Enter your email to find your user ID:")
    email = input("Email: ").strip()

    try:
        result = client.table("users").select("id, email").eq("email", email).execute()

        if not result.data:
            print(f"❌ No user found with email: {email}")
            return False

        user_id = result.data[0]["id"]
        print(f"✅ Found user: {email}")
        print(f"   User ID: {user_id}\n")

    except Exception as e:
        print(f"❌ Error finding user: {e}")
        return False

    # Create test notifications
    print("🔔 Creating test notifications...\n")

    # Test 1: New episode notification
    print("1. Creating 'New Episode' notification...")
    success = notifications.create_notification(
        client=client,
        user_id=user_id,
        notification_type="new_episode",
        title="New Episode Available!",
        message="A new episode is airing today",
        related_show_id=66732,
        related_show_title="Stranger Things",
        send_email=False
    )
    print(f"   {'✅ Created' if success else '❌ Failed'}")

    # Test 2: Show added notification
    print("\n2. Creating 'Show Added' notification...")
    success = notifications.create_notification(
        client=client,
        user_id=user_id,
        notification_type="status_change",
        title="Show Status Changed",
        message="The Office has been added to your watchlist.",
        related_show_id=2316,
        related_show_title="The Office",
        send_email=False
    )
    print(f"   {'✅ Created' if success else '❌ Failed'}")

    # Test 3: Reminder notification
    print("\n3. Creating 'Reminder' notification...")
    success = notifications.create_notification(
        client=client,
        user_id=user_id,
        notification_type="reminder",
        title="Don't forget to watch!",
        message="You have 3 shows airing this week",
        send_email=False
    )
    print(f"   {'✅ Created' if success else '❌ Failed'}")

    # Test 4: System notification
    print("\n4. Creating 'System' notification...")
    success = notifications.create_notification(
        client=client,
        user_id=user_id,
        notification_type="system",
        title="Welcome to Notifications!",
        message="StreamGenie now has in-app notifications. Stay updated on your favorite shows!",
        send_email=False
    )
    print(f"   {'✅ Created' if success else '❌ Failed'}")

    # Get notification count
    print("\n" + "="*50)
    count = notifications.get_unread_count(client, user_id)
    print(f"✅ You now have {count} unread notifications!")
    print("="*50)

    print("\n📱 Open http://localhost:8501 to see your notifications in the sidebar!")

    return True

if __name__ == "__main__":
    print("="*50)
    print("🔔 StreamGenie Notifications Test")
    print("="*50)
    print()

    success = test_notifications()

    if success:
        print("\n✅ Test successful!")
    else:
        print("\n❌ Test failed!")
        exit(1)
