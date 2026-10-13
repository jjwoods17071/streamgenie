"""
Memoization with a TTL, independent of any runtime.

WHY NOT @st.cache_data: these modules are the future API (see ROADMAP.md), and a module
that imports streamlit cannot be imported by a FastAPI worker, a cron job or a test
without dragging a UI framework in. Replacing the decorator — rather than injecting a
cache object at every call site — keeps the call sites unchanged.

It also removes a real hazard. st.cache_data computes its key via inspect.getsource(),
which indexes CURRENT line numbers into linecache's CACHED file contents; when a deploy
rewrites a file under a live process those disagree and tokenizing starts mid-docstring.
That took the whole app down once (see CLAUDE.md). This keys on the arguments instead, so
editing a file can't produce a cache key at all.

Convention kept from st.cache_data: a parameter whose name starts with "_" is NOT part of
the key. That is how the Supabase client gets passed to a cached function without being
hashed.
"""
import functools
import inspect
import threading
import time
from typing import Any, Callable, Dict, Tuple

_LOCK = threading.RLock()
_STORE: Dict[str, Dict[Tuple, Tuple[float, Any]]] = {}


def memoize(ttl: int = 300, show_spinner: bool = False) -> Callable:
    """Cache a function's result for `ttl` seconds, keyed on its arguments.

    show_spinner is accepted and ignored — it exists so the st.cache_data call sites this
    replaced could keep their keyword without a diff on every line.
    """
    def decorate(fn: Callable) -> Callable:
        # Resolved once, at decoration. Never per call, and never from source text.
        try:
            params = list(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            params = []
        skip = {i for i, name in enumerate(params) if name.startswith("_")}
        skip_names = {name for name in params if name.startswith("_")}
        bucket = f"{fn.__module__}.{fn.__qualname__}"
        _STORE.setdefault(bucket, {})

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key_args = tuple(a for i, a in enumerate(args) if i not in skip)
            key_kwargs = tuple(sorted((k, v) for k, v in kwargs.items()
                                      if k not in skip_names))
            try:
                key = (key_args, key_kwargs)
                hash(key)
            except TypeError:
                # An unhashable argument means we can't cache this call. Compute it
                # rather than raise — a cache is an optimisation, never a precondition.
                return fn(*args, **kwargs)

            now = time.monotonic()
            with _LOCK:
                hit = _STORE[bucket].get(key)
                if hit is not None and hit[0] > now:
                    return hit[1]

            value = fn(*args, **kwargs)          # computed OUTSIDE the lock
            with _LOCK:
                _STORE[bucket][key] = (now + ttl, value)
            return value

        wrapper.cache_clear = lambda: _clear_bucket(bucket)
        return wrapper
    return decorate


def _clear_bucket(bucket: str) -> None:
    with _LOCK:
        _STORE[bucket] = {}


def clear() -> None:
    """Drop everything. Wired to the admin "Rebuild caches" button beside
    st.cache_data.clear(), which only reaches the caches still using Streamlit's."""
    with _LOCK:
        for bucket in _STORE:
            _STORE[bucket] = {}


def stats() -> Dict[str, int]:
    """Live entry count per function. For the self-test and for answering "is this
    actually caching?" without reading the implementation."""
    with _LOCK:
        return {b: len(v) for b, v in _STORE.items()}
