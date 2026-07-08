"""
Supabase client factory.

Reads SUPABASE_URL and SUPABASE_SERVICE_KEY from the environment - from a
local .env in dev (see .env.example), or from GitHub Actions secrets in CI.
The service role key is required: RLS is enabled on ticker/prices with no
public policies, so only the service role can read or write them.
"""

import os

from supabase import create_client, Client

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_client() -> Client:
    """Build a fresh client, or raise if SUPABASE_URL/SUPABASE_SERVICE_KEY
    are missing. Used by one-off scripts, which should hard-fail on missing
    config rather than silently doing nothing."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


_client_singleton: Client | None = None
_client_init_attempted = False


def get_client_optional() -> Client | None:
    """Lazily create and memoize a client for the FastAPI request hot path.

    Never raises - returns None if SUPABASE_URL/SUPABASE_SERVICE_KEY are
    unset or client construction otherwise fails, so the backend can boot
    and serve (via live yfinance fallback) with zero Supabase config.

    Only construction failure is memoized (a permanent local-config issue).
    Query failures happen later, inside each caller's own .execute() calls,
    so a transient Supabase outage self-heals on the next request without
    needing a server restart.
    """
    global _client_singleton, _client_init_attempted
    if _client_init_attempted:
        return _client_singleton
    _client_init_attempted = True
    try:
        _client_singleton = get_client()
    except Exception:
        _client_singleton = None
    return _client_singleton
