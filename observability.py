"""
Error reporting. One place, so the Streamlit app, the cron and the future API all report
the same way.

WHY: production failures in this project are found by Joe, by hand, and pasted in. A
truncated traceback once cost a full wrong-root-cause round, and "Not interested" shipped
as a RecursionError that nobody noticed because nothing reported it — it was found weeks
later while auditing something else.

Degrades to a no-op with no DSN and with no sentry_sdk installed, per PRODUCT.md
principle 6: the feature gets quieter, it doesn't crash. Runtime-agnostic (no streamlit).
"""
import logging
import os
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_enabled = False


def init(dsn: Optional[str] = None, release: Optional[str] = None,
         environment: str = "production") -> bool:
    """Start reporting. True if it actually started.

    PII is deliberately OFF. We hold email addresses and viewing history, and a crash
    report is not a place either belongs — Sentry's default is already not to send it,
    but it is set explicitly here so a library default change can't quietly opt us in.
    """
    global _enabled
    if _enabled:
        return True
    dsn = dsn or os.getenv("SENTRY_DSN") or ""
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.info("SENTRY_DSN is set but sentry-sdk isn't installed")
        return False
    try:
        sentry_sdk.init(
            dsn=dsn,
            release=release,
            environment=environment,
            send_default_pii=False,       # we hold emails; never attach them
            # Performance tracing costs quota and answers a question nobody is asking.
            # The point here is "tell me it broke", not "tell me it was slow".
            traces_sample_rate=0.0,
            max_breadcrumbs=30,
            before_send=_scrub,
        )
        _enabled = True
        return True
    except Exception as e:                # a broken DSN must not take the app down
        log.warning("sentry init failed: %s", e)
        return False


_SECRET_HINTS = ("key", "token", "secret", "password", "dsn", "authorization", "cookie")


def _scrub(event: Dict[str, Any], hint: Dict[str, Any]) -> Dict[str, Any]:
    """Drop anything that looks like a credential or an address.

    The app reads TMDB, Anthropic and Supabase keys from the environment, and Sentry
    attaches local variables to stack frames — so a key sitting in a local is exactly the
    kind of thing that leaves in a crash report without anyone intending it.
    """
    try:
        event.pop("user", None)
        for exc in (event.get("exception") or {}).get("values") or []:
            for frame in (exc.get("stacktrace") or {}).get("frames") or []:
                v = frame.get("vars")
                if not isinstance(v, dict):
                    continue
                for name in list(v):
                    low = name.lower()
                    if any(h in low for h in _SECRET_HINTS) or "@" in str(v[name]):
                        v[name] = "[scrubbed]"
    except Exception:
        pass                              # never let scrubbing break reporting
    return event


def enabled() -> bool:
    return _enabled


def capture(error: BaseException, **tags) -> None:
    """Report a caught exception that the app is choosing to handle.

    For the places that legitimately swallow — a background refresh, an optional
    enrichment — so "it quietly stopped working" becomes visible without becoming a
    user-facing crash.
    """
    log.warning("%s: %s %s", type(error).__name__, error, tags or "")
    if not _enabled:
        return
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            for k, v in tags.items():
                scope.set_tag(k, str(v)[:200])
            sentry_sdk.capture_exception(error)
    except Exception:
        pass
