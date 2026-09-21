"""
Freshness - whether the data being read comes from a recent run of the daily
fetch job or an old one (issue #154, docs/adr/0003-the-daily-job-records-its-own-runs.md).

The model, in three parts:

  - **The job records itself.** `scripts/fetch_daily.py` writes one `fetch_run`
    row when its price sync ends: a `finished_at` timestamp (stamped by the
    database) and how many ids failed. This module reads the newest one. It is
    deliberately not derived from `ticker.last_fetch`: that is a date on the
    runner's UTC clock, GitHub starts the cron hours late, and one date can
    then mean either of two days' runs.
  - **The backend names the deadline; the browser does the comparing.**
    `due_by` is the moment after which, if no newer run has finished, the data
    is behind: the first scheduled slot strictly after the run finished, plus
    the grace. The browser compares that with its own clock, so the answer can
    be cached for minutes yet still turn from on-schedule to behind on time,
    and no calendar logic lives in the client. The schedule is in `config.py`
    (with a test guarding it against the workflow file), in exactly one place.
  - **Absence is never a verdict.** No Supabase configured, nothing yet
    recorded, and a table not yet created all answer `finishedAt`/`dueBy`/`failed`
    all `None`: the browser reads that as "unknown", not as behind and not as a
    date (invariant 7). A database that is configured but cannot be reached or
    read is a different fact - a fact about right now - and raises
    `DataUnavailable`, which main.py turns into the 503 the frontend retries
    (invariant 1).

This says nothing about how old the latest price is. A market holiday adds no
prices and the job still ran; that is the same freshness, not a stale one.
"""

import os
from datetime import datetime, time, timedelta, timezone

from config import (
    CACHE_TTL_SECONDS,
    FETCH_GRACE_HOURS,
    FETCH_SCHEDULE_HOUR_UTC,
    FETCH_SCHEDULE_MINUTE_UTC,
    FETCH_SCHEDULE_WEEKDAYS,
)
from services.cache import cache
from services.market_data import DataUnavailable
from services.supabase_client import get_client_optional

_CACHE_KEY = "freshness"

# PostgREST / Postgres codes for "this table does not exist (yet)": PGRST205,
# the table is not in PostgREST's schema cache; 42P01, undefined_table.
_TABLE_MISSING_CODES = ("PGRST205", "42P01")


def due_by(finished_at: datetime) -> datetime:
    """The moment after which a run that finished at `finished_at` no longer
    counts as recent: the next scheduled slot strictly after it, plus the grace.

    Measured from when the run *finished*, never from which day it was
    scheduled for. A Friday run GitHub started after midnight UTC finishes on
    Saturday and a Thursday run started late finishes on Friday; both look
    ahead to the slot that is actually still to come (Monday's, and Friday's),
    which is what lets a Friday run that never happens be caught on Saturday
    morning rather than the Tuesday after. A run that finishes exactly on a
    slot looks ahead to the following one.

    A `finished_at` with no timezone is refused rather than assumed to be UTC.
    """
    if finished_at.tzinfo is None:
        raise ValueError("finished_at must carry a timezone")
    finished = finished_at.astimezone(timezone.utc)

    slot_time = time(FETCH_SCHEDULE_HOUR_UTC, FETCH_SCHEDULE_MINUTE_UTC)
    # A week always contains the next slot for any non-empty schedule; the
    # eighth day only covers finishing on a scheduled day after its slot.
    for offset in range(8):
        day = finished.date() + timedelta(days=offset)
        if day.weekday() not in FETCH_SCHEDULE_WEEKDAYS:
            continue
        slot = datetime.combine(day, slot_time, tzinfo=timezone.utc)
        if slot > finished:
            return slot + timedelta(hours=FETCH_GRACE_HOURS)
    raise ValueError("FETCH_SCHEDULE_WEEKDAYS names no weekday")


def get_freshness() -> dict:
    """The newest recorded run of the daily job: `finishedAt` (UTC, ISO 8601),
    `dueBy` (see `due_by`) and `failed` (how many ids the run could not
    refresh; zero is a finding, not an absence).

    All three are `None` when there is nothing to describe, which the frontend
    reads as unknown: Supabase is not configured, no run has been recorded yet,
    or the `fetch_run` table has not been created (`sql/005` not applied yet -
    the backend can be deployed first, and asking again will not change that).

    A configured database that cannot be read raises `DataUnavailable` (503,
    retried), never an empty answer: "the database is down" and "nobody has run
    the job yet" must not look alike. That includes credentials being set but no
    client being buildable - `get_client_optional` returns None for a cold
    process whose DNS or TLS is not ready yet exactly as it does for a missing
    config, and only the environment says which. A permanent 200 there would
    leave the header on unknown for a whole session (the frontend asks once).

    Only a found run is cached (`CACHE_TTL_SECONDS`), because the answer only
    changes once a day. An absent answer is deliberately not: an empty table is
    one run away from its first row, and a missing one from being created.
    Remembering either would keep the header on unknown for a quarter of an hour
    after the fact had changed. A failure is never cached, the same rule every
    cached read here follows.

    The read is `LIMIT 1` over a table that gains a row per run, so it never
    approaches PostgREST's row cap (invariant 3).
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return dict(cached)

    db = get_client_optional()
    if db is None:
        if _supabase_configured():
            raise DataUnavailable("could not connect to Supabase")
        return _unknown()

    try:
        rows = (
            db.table("fetch_run")
            .select("finished_at,failed")
            .order("finished_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
    except Exception as exc:
        if getattr(exc, "code", None) in _TABLE_MISSING_CODES:
            return _unknown()
        raise DataUnavailable("could not read the daily job's run record") from exc
    if not rows:
        return _unknown()

    finished_at = datetime.fromisoformat(rows[0]["finished_at"]).astimezone(timezone.utc)
    result = {
        "finishedAt": finished_at.isoformat(),
        "dueBy": due_by(finished_at).isoformat(),
        "failed": int(rows[0]["failed"]),
    }
    cache.set(_CACHE_KEY, result, CACHE_TTL_SECONDS)
    return dict(result)


def _unknown() -> dict:
    return {"finishedAt": None, "dueBy": None, "failed": None}


def _supabase_configured() -> bool:
    """Whether the credentials `get_client` needs are set at all - the only way
    to tell "not configured" (a permanent condition) from "could not connect"
    (a blip), since `get_client_optional` answers None for both."""
    return bool(os.environ.get("SUPABASE_URL")) and bool(os.environ.get("SUPABASE_SERVICE_KEY"))
