"""
Authentication module for StreamGenie
Handles user signup, login, logout, session management, and user roles
"""
import os
import streamlit as st
from supabase import Client
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Base URL the password-reset link returns to. Defaults to the hosted app; set
# APP_BASE_URL=http://localhost:8501 in a local .env to test resets in dev.
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://streamgenie-estero.streamlit.app").rstrip("/")

# ---------------- Persistent login (browser cookie) ----------------
# Streamlit session state is wiped when the WebSocket drops (phone screen-lock,
# tab backgrounded). We persist the Supabase refresh token in a cookie so the
# session can be restored on reconnect. Everything below is fail-safe: if the
# cookie component is unavailable or errors, we silently fall back to the normal
# login screen — never a lockout.
try:
    import extra_streamlit_components as stx
except Exception:
    stx = None

_COOKIE_NAME = "sg_session"


def _js_set_cookie(value: str, max_age: int):
    """Write the session cookie via inline JS. components.html renders a same-origin
    srcdoc iframe, so document.cookie lands on the app's domain. No round-trip
    component state to race with (the old stx CookieManager lost the write whenever
    st.rerun() fired before its iframe mounted)."""
    try:
        import streamlit.components.v1 as components
        components.html(
            f"<script>document.cookie = '{_COOKIE_NAME}={value}; max-age={max_age}; "
            f"path=/; samesite=lax' + (location.protocol === 'https:' ? '; secure' : '');</script>",
            height=0,
        )
    except Exception:
        pass


def persist_session(refresh_token: Optional[str]):
    """Store the Supabase refresh token in a 30-day cookie."""
    if refresh_token:
        _js_set_cookie(refresh_token, 30 * 24 * 3600)


def clear_persisted_session():
    _js_set_cookie("", 0)


def restore_session(client: Client) -> bool:
    """If there's no in-memory user but a valid refresh-token cookie exists,
    refresh the Supabase session and restore login. Returns True if restored.

    Reads via st.context.cookies — the cookies the browser sent when this
    session connected. Available synchronously on the FIRST run (no component
    mount/rerun dance), so a page refresh restores login with no flash."""
    if st.session_state.get("user"):
        return False
    try:
        rt = st.context.cookies.get(_COOKIE_NAME)
    except Exception:
        rt = None
    if not rt:
        return False
    try:
        # Throwaway client so we don't mutate the cached (shared) service-role client
        from supabase import create_client
        tmp = create_client(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_KEY", ""))
        res = tmp.auth.refresh_session(rt)
        if res and getattr(res, "user", None):
            st.session_state.user = {"id": res.user.id, "email": res.user.email}
            ensure_user_record(client, res.user.id, res.user.email)
            # Supabase rotates refresh tokens — persist the new one for next time
            new_rt = getattr(getattr(res, "session", None), "refresh_token", None)
            if new_rt:
                st.session_state["_sg_pending_rt"] = new_rt  # flushed on stable render
            return True
    except Exception:
        # expired / invalid cookie — drop it and show the login screen
        clear_persisted_session()
    return False


def flush_pending_session():
    """Write a login's queued refresh token to the cookie. Called from the main
    app body AFTER authentication, where the render completes without an
    immediate rerun — so the cookie write actually lands in the browser."""
    rt = st.session_state.pop("_sg_pending_rt", None)
    if rt:
        persist_session(rt)


def init_auth_session():
    """Initialize authentication session state"""
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'auth_mode' not in st.session_state:
        st.session_state.auth_mode = 'login'  # 'login' or 'signup'
    if 'show_forgot_password' not in st.session_state:
        st.session_state.show_forgot_password = False


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


def ensure_user_record(client: Client, user_id: str, email: Optional[str]) -> bool:
    """
    Guarantee a public.users row exists for this auth user.

    The shows/notifications/etc. tables FK onto users(id); a user created via the
    Supabase dashboard (or lost in a restore) can authenticate but has no users row,
    which makes inserts fail with shows_user_id_fkey. Upsert is idempotent.
    """
    if not user_id:
        return False
    try:
        client.table("users").upsert({
            "id": user_id,
            "email": email,
            "username": (email or "user").split('@')[0] or "user",
        }, on_conflict="id").execute()
        return True
    except Exception as e:
        print(f"ensure_user_record warning: {e}")
        return False


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
            st.session_state["_sg_pending_rt"] = getattr(
                getattr(response, "session", None), "refresh_token", None)  # flushed next render
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
            # Self-heal: guarantee the public.users FK parent row exists
            ensure_user_record(client, response.user.id, response.user.email)
            # Don't write the cookie here: the caller st.rerun()s immediately, which
            # unmounts the cookie component before it can save. Queue the token and
            # flush_pending_session() writes it on the next (stable) render.
            st.session_state["_sg_pending_rt"] = getattr(
                getattr(response, "session", None), "refresh_token", None)
            return True, f"Welcome back, {email}!"
        else:
            return False, "Invalid email or password."

    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
            return False, "Invalid email or password."
        else:
            return False, f"Error: {error_msg}"


def reset_password_request(client: Client, email: str) -> tuple[bool, str]:
    """
    Request a password reset email
    Returns: (success: bool, message: str)
    """
    try:
        # Supabase will send a password reset email to this address
        response = client.auth.reset_password_for_email(
            email,
            options={
                "redirect_to": APP_BASE_URL  # env-aware: hosted by default, localhost in dev
            }
        )

        return True, f"Password reset email sent to {email}! Check your inbox and spam folder."

    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            # Don't reveal if email exists or not for security
            return True, f"If an account exists for {email}, a password reset email has been sent."
        else:
            return False, f"Error: {error_msg}"


def inject_recovery_hash_shim():
    """Supabase recovery links return the token in the URL #fragment, which Streamlit
    (server-side) can't read. This JS reads the parent window's hash and, if it's a
    recovery link, rewrites the URL to query params (?recovery=1&at=...&rt=...) so the
    Python side can pick it up."""
    import streamlit.components.v1 as components
    components.html(
        """
        <script>
        (function () {
          try {
            var h = window.parent.location.hash || "";
            if (h.indexOf("type=recovery") !== -1 && h.indexOf("access_token") !== -1) {
              var p = new URLSearchParams(h.substring(1));
              var at = p.get("access_token");
              var rt = p.get("refresh_token") || "";
              var base = window.parent.location.origin + window.parent.location.pathname;
              window.parent.location.replace(
                base + "?recovery=1&at=" + encodeURIComponent(at) + "&rt=" + encodeURIComponent(rt)
              );
            }
          } catch (e) { /* cross-origin or no hash: ignore */ }
        })();
        </script>
        """,
        height=0,
    )


def handle_password_recovery(client: Client) -> bool:
    """If the URL carries a recovery token (via the shim above), show a set-new-password
    form. Returns True if recovery is in progress (caller should st.stop())."""
    qp = st.query_params
    if qp.get("recovery") != "1" or not qp.get("at"):
        return False

    access_token = qp.get("at")
    refresh_token = qp.get("rt", "")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("### 🔒 Set a New Password")
        st.caption("Choose a new password for your StreamGenie account.")
        pw1 = st.text_input("New password", type="password", key="rec_pw1")
        pw2 = st.text_input("Confirm new password", type="password", key="rec_pw2")
        if st.button("Update Password", type="primary", use_container_width=True):
            if len(pw1) < 6:
                st.error("Password must be at least 6 characters.")
            elif pw1 != pw2:
                st.error("Passwords don't match.")
            else:
                try:
                    client.auth.set_session(access_token, refresh_token)
                    client.auth.update_user({"password": pw1})
                    client.auth.sign_out()
                    st.session_state.user = None
                    st.success("✅ Password updated! Returning to login…")
                    st.query_params.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Reset failed — the link may have expired (they last 1 hour, single use). {e}")
        st.caption("Reset links expire after 1 hour and can only be used once.")
    return True


def logout_user(client: Client):
    """Log out the current user"""
    try:
        clear_persisted_session()
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
            # Check if user wants to reset password
            if st.session_state.get('show_forgot_password', False):
                st.markdown("**Reset Your Password**")
                st.caption("Enter your email address and we'll send you a link to reset your password.")

                reset_email = st.text_input("Email", key="reset_email", placeholder="your@email.com")

                col_send, col_back = st.columns([1, 1])
                with col_send:
                    if st.button("📧 Send Reset Link", use_container_width=True, type="primary"):
                        if not reset_email:
                            st.error("Please enter your email address")
                        else:
                            success, message = reset_password_request(client, reset_email)
                            if success:
                                st.success(message)
                            else:
                                st.error(message)

                with col_back:
                    if st.button("⬅️ Back to Login", use_container_width=True):
                        st.session_state.show_forgot_password = False
                        st.rerun()

            else:
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
                        st.session_state.show_forgot_password = True
                        st.rerun()

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
