"""
Authentication module for StreamGenie
Handles user signup, login, logout, session management, and user roles
"""
import streamlit as st
from supabase import Client
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


def init_auth_session():
    """Initialize authentication session state"""
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'auth_mode' not in st.session_state:
        st.session_state.auth_mode = 'login'  # 'login' or 'signup'


def get_current_user() -> Optional[Dict[str, Any]]:
    """Get the currently authenticated user"""
    return st.session_state.get('user')


def is_authenticated() -> bool:
    """Check if user is authenticated"""
    return st.session_state.get('user') is not None


def get_user_id() -> Optional[str]:
    """Get the current user's ID"""
    user = get_current_user()
    return user['id'] if user else None


def signup_user(client: Client, email: str, password: str) -> tuple[bool, str]:
    """
    Sign up a new user
    Returns: (success: bool, message: str)
    """
    try:
        response = client.auth.sign_up({
            "email": email,
            "password": password
        })

        if response.user:
            # Create user in public.users table for foreign key relationships
            try:
                client.table("users").insert({
                    "id": response.user.id,
                    "email": response.user.email,
                    "username": email.split('@')[0]
                }).execute()
            except Exception as e:
                # User might already exist, that's okay
                if "duplicate" not in str(e).lower():
                    print(f"Warning: Could not create user in users table: {e}")

            st.session_state.user = {
                'id': response.user.id,
                'email': response.user.email
            }
            return True, "Account created successfully! Welcome to StreamGenie!"
        else:
            return False, "Failed to create account. Please try again."

    except Exception as e:
        error_msg = str(e)
        if "already registered" in error_msg.lower():
            return False, "This email is already registered. Please log in instead."
        elif "password" in error_msg.lower():
            return False, "Password must be at least 6 characters long."
        else:
            return False, f"Error: {error_msg}"


def login_user(client: Client, email: str, password: str) -> tuple[bool, str]:
    """
    Log in an existing user
    Returns: (success: bool, message: str)
    """
    try:
        response = client.auth.sign_in_with_password({
            "email": email,
            "password": password
        })

        if response.user:
            st.session_state.user = {
                'id': response.user.id,
                'email': response.user.email
            }
            return True, f"Welcome back, {email}!"
        else:
            return False, "Invalid email or password."

    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
            return False, "Invalid email or password."
        else:
            return False, f"Error: {error_msg}"


def logout_user(client: Client):
    """Log out the current user"""
    try:
        client.auth.sign_out()
        st.session_state.user = None
        st.success("Logged out successfully!")
    except Exception as e:
        st.error(f"Error logging out: {e}")


def render_auth_ui(client: Client):
    """Render the authentication UI (login/signup form)"""

    # Center the auth form
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("### 🍿 Welcome to StreamGenie")

        # Toggle between login and signup
        auth_mode = st.session_state.get('auth_mode', 'login')

        tab1, tab2 = st.tabs(["🔑 Login", "📝 Sign Up"])

        with tab1:
            st.markdown("**Log in to your account**")
            login_email = st.text_input("Email", key="login_email", placeholder="your@email.com")
            login_password = st.text_input("Password", type="password", key="login_password")

            col_login, col_forgot = st.columns([1, 1])
            with col_login:
                if st.button("🔓 Log In", use_container_width=True, type="primary"):
                    if not login_email or not login_password:
                        st.error("Please enter both email and password")
                    else:
                        success, message = login_user(client, login_email, login_password)
                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)

            with col_forgot:
                if st.button("🔄 Forgot Password?", use_container_width=True):
                    st.info("Password reset coming soon! Contact support for now.")

        with tab2:
            st.markdown("**Create a new account**")
            signup_email = st.text_input("Email", key="signup_email", placeholder="your@email.com")
            signup_password = st.text_input("Password", type="password", key="signup_password",
                                           help="Minimum 6 characters")
            signup_password_confirm = st.text_input("Confirm Password", type="password",
                                                    key="signup_password_confirm")

            if st.button("✨ Create Account", use_container_width=True, type="primary"):
                if not signup_email or not signup_password:
                    st.error("Please enter both email and password")
                elif signup_password != signup_password_confirm:
                    st.error("Passwords don't match")
                elif len(signup_password) < 6:
                    st.error("Password must be at least 6 characters")
                else:
                    success, message = signup_user(client, signup_email, signup_password)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

        st.markdown("---")
        st.caption("🔒 Your data is secure and encrypted")


def render_user_menu(client: Client):
    """Render the user menu for authenticated users"""
    user = get_current_user()
    if not user:
        return

    with st.sidebar:
        st.markdown("---")
        st.markdown(f"**👤 {user['email']}**")

        if st.button("🚪 Logout", use_container_width=True):
            logout_user(client)
            st.rerun()


# ========================================
# Role-Based Access Control Functions
# ========================================

def get_user_role(client: Client, user_id: str) -> str:
    """
    Get the role for a user

    Args:
        client: Supabase client
        user_id: User ID

    Returns:
        User role string ('user', 'admin') or 'user' if error
    """
    try:
        result = client.table("users")\
            .select("user_role")\
            .eq("id", user_id)\
            .execute()

        if result.data and len(result.data) > 0:
            return result.data[0].get("user_role", "user")

        # Default to 'user' if no role found
        return "user"

    except Exception as e:
        logger.error(f"Error getting user role: {e}")
        return "user"  # Fail safely to regular user


def is_admin(client: Client, user_id: str) -> bool:
    """
    Check if user is an admin

    Args:
        client: Supabase client
        user_id: User ID

    Returns:
        True if user is admin, False otherwise
    """
    role = get_user_role(client, user_id)
    return role == "admin"


def require_admin(client: Client, user_id: str) -> bool:
    """
    Check if user is admin, raise exception if not

    Args:
        client: Supabase client
        user_id: User ID

    Returns:
        True if admin

    Raises:
        PermissionError if user is not admin
    """
    if not is_admin(client, user_id):
        raise PermissionError("Admin access required")
    return True


def set_user_role(client: Client, user_id: str, role: str) -> bool:
    """
    Set the role for a user (admin only)

    Args:
        client: Supabase client
        user_id: User ID to update
        role: New role ('user', 'admin')

    Returns:
        True if successful, False otherwise
    """
    try:
        # Validate role
        if role not in ["user", "admin"]:
            logger.error(f"Invalid role: {role}")
            return False

        # Update role
        client.table("users")\
            .update({"user_role": role})\
            .eq("id", user_id)\
            .execute()

        logger.info(f"Updated user {user_id} role to {role}")
        return True

    except Exception as e:
        logger.error(f"Error setting user role: {e}")
        return False


def get_user_email_by_id(client: Client, user_id: str) -> Optional[str]:
    """
    Get email for a user

    Args:
        client: Supabase client
        user_id: User ID

    Returns:
        User email or None if not found
    """
    try:
        result = client.table("users")\
            .select("email")\
            .eq("id", user_id)\
            .execute()

        if result.data and len(result.data) > 0:
            return result.data[0].get("email")

        return None

    except Exception as e:
        logger.error(f"Error getting user email: {e}")
        return None


def list_admins(client: Client) -> list:
    """
    Get list of all admin users

    Args:
        client: Supabase client

    Returns:
        List of admin user dictionaries with id, email, user_role
    """
    try:
        result = client.table("users")\
            .select("id, email, user_role")\
            .eq("user_role", "admin")\
            .execute()

        return result.data if result.data else []

    except Exception as e:
        logger.error(f"Error listing admins: {e}")
        return []


def list_all_users(client: Client) -> list:
    """
    Get list of all users

    Args:
        client: Supabase client

    Returns:
        List of user dictionaries with id, email, user_role, created_at
    """
    try:
        result = client.table("users")\
            .select("id, email, user_role, created_at")\
            .order("created_at", desc=True)\
            .execute()

        return result.data if result.data else []

    except Exception as e:
        logger.error(f"Error listing users: {e}")
        return []


def promote_to_admin(client: Client, user_id: str, admin_user_id: str) -> tuple[bool, str]:
    """
    Promote a user to admin role (admin only)

    Args:
        client: Supabase client
        user_id: User ID to promote
        admin_user_id: ID of admin performing the action

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Check if requester is admin
        if not is_admin(client, admin_user_id):
            return False, "Only admins can promote users"

        # Get user email for logging
        user_email = get_user_email_by_id(client, user_id)
        if not user_email:
            return False, "User not found"

        # Update role
        success = set_user_role(client, user_id, "admin")

        if success:
            logger.info(f"Admin {admin_user_id} promoted {user_email} to admin")
            return True, f"Successfully promoted {user_email} to admin"
        else:
            return False, "Failed to update user role"

    except Exception as e:
        logger.error(f"Error promoting user to admin: {e}")
        return False, f"Error: {e}"


def demote_to_user(client: Client, user_id: str, admin_user_id: str) -> tuple[bool, str]:
    """
    Demote an admin to regular user role (admin only)

    Args:
        client: Supabase client
        user_id: User ID to demote
        admin_user_id: ID of admin performing the action

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Check if requester is admin
        if not is_admin(client, admin_user_id):
            return False, "Only admins can demote users"

        # Prevent self-demotion
        if user_id == admin_user_id:
            return False, "You cannot demote yourself"

        # Check if this would leave no admins
        admins = list_admins(client)
        if len(admins) <= 1:
            return False, "Cannot demote the last admin. Promote another user first."

        # Get user email for logging
        user_email = get_user_email_by_id(client, user_id)
        if not user_email:
            return False, "User not found"

        # Update role
        success = set_user_role(client, user_id, "user")

        if success:
            logger.info(f"Admin {admin_user_id} demoted {user_email} to regular user")
            return True, f"Successfully demoted {user_email} to regular user"
        else:
            return False, "Failed to update user role"

    except Exception as e:
        logger.error(f"Error demoting admin to user: {e}")
        return False, f"Error: {e}"
