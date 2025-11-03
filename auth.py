"""
Authentication module for StreamGenie
Handles user signup, login, logout, and session management
"""
import streamlit as st
from supabase import Client
from typing import Optional, Dict, Any


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
