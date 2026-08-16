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


# PostgREST caps a single response at this many rows by default (Supabase's
# "Max Rows" setting) and returns the truncated page with no error - a plain
# .select().execute() over a table/queryset that can grow past this silently
# acts on partial data (see issue #14). Any read whose row count scales with
# the data (a whole table, or a filter that isn't inherently tiny) must go
# through paginated_select() below rather than a bare .execute().
SUPABASE_PAGE_SIZE = 1000


def paginated_select(build_query, page_size: int = SUPABASE_PAGE_SIZE) -> list[dict]:
    """Run a select to completion by paging with .range() until a short
    page comes back, so results past PostgREST's row cap are never silently
    dropped.

    `build_query` must be a zero-arg callable that returns a FRESH query
    builder every call, e.g.:

        paginated_select(lambda: client.table("t").select("*").eq("x", 1))

    A fresh builder per page is required, not just a reused one re-ranged:
    postgrest-py's .range() *adds* offset/limit query params rather than
    replacing them, so calling .range() again on the same builder object
    would accumulate stale params instead of advancing the window. Callers
    should also give the query a deterministic ORDER BY (ideally over a
    unique key, or a key that's unique within the filtered set) - paging
    with .range() re-issues a separate query per page, and without a stable
    sort Postgres doesn't guarantee the same row ordering across those
    calls, which can skip or duplicate rows at page boundaries.
    """
    rows: list[dict] = []
    offset = 0
    while True:
        page = build_query().range(offset, offset + page_size - 1).execute().data
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def assert_not_truncated(rows: list[dict], page_size: int = SUPABASE_PAGE_SIZE) -> list[dict]:
    """Raise if a deliberately non-paginated read came back with exactly the
    PostgREST page cap - almost certainly a silent truncation rather than a
    genuine coincidence. Use this on selects that are expected to always
    stay well under the cap (so full pagination would be overkill), as a
    safety net that turns a future truncation loud instead of letting the
    caller silently act on a partial result.
    """
    if len(rows) == page_size:
        raise RuntimeError(
            f"read returned exactly {page_size} rows - likely truncated by "
            "PostgREST's page cap; switch this read to paginated_select()"
        )
    return rows


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
