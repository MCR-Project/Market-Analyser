"""
Tests for Freshness (issue #154): whether the data being read comes from a
recent run of the daily fetch job or an old one.

Three layers, each tested through its public function only:

  - `services.freshness.due_by` - the deadline arithmetic. Every expected value
    is a worked example off the schedule in `.github/workflows/fetch-daily.yml`
    (22:30 UTC, Monday to Friday) plus the 12-hour grace, written out as a
    literal, never recomputed the way the code computes it. Several of them are
    the real shape of the problem the run record exists for (docs/adr/0003): a
    Friday run that GitHub started after midnight UTC finishes on Saturday, and a
    Thursday run started late finishes on Friday - a date alone cannot tell the
    two apart, a timestamp against the next scheduled slot can.
  - `services.freshness.get_freshness` - reads the newest `fetch_run` row and
    answers `finishedAt`/`dueBy`/`failed`. No test here reaches Supabase: the
    client is a small fake, patched in at `get_client_optional`.
  - `GET /api/freshness` - the status-code contract (backend/CLAUDE.md, "Errors
    are the API"): nothing to report is a 200 of nulls, a database that cannot
    be read is a 503 the frontend retries, and never a 500.

The schedule this module keeps (`config.py`) is a second copy of the cron line,
so one test reads the workflow file and fails if the two differ.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import config
from main import app
from services.cache import TTLCache
from services.freshness import due_by, get_freshness
from services.market_data import DataUnavailable

client = TestClient(app, raise_server_exceptions=False)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def utc(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


# 2026-09-18 is a Friday, so 09-14 is a Monday and 09-21 the Monday after.

class DueByTests(unittest.TestCase):
    def test_a_run_that_started_on_time_is_due_at_the_next_slots_grace(self):
        """Friday's run finishing at 22:33 UTC: the next slot is Monday 22:30,
        so nothing newer is expected before Tuesday 10:30 (that plus 12h)."""
        self.assertEqual(due_by(utc(2026, 9, 18, 22, 33)), utc(2026, 9, 22, 10, 30))

    def test_a_friday_run_started_after_midnight_is_still_friday_s(self):
        """GitHub started Friday's run at 00:25 UTC on Saturday and it finished
        00:28. Its next slot is still Monday's, the same deadline as the run
        that started on time - the case a date-only stamp reads as Saturday."""
        self.assertEqual(due_by(utc(2026, 9, 19, 0, 28)), utc(2026, 9, 22, 10, 30))

    def test_a_thursday_run_finishing_on_friday_is_due_the_next_morning(self):
        """Thursday's run started late and finished Friday 00:30 UTC. Friday's
        own slot is still to come, so the deadline is Saturday 10:30 - and a
        Friday run that never happens is caught then, not on Tuesday."""
        self.assertEqual(due_by(utc(2026, 9, 18, 0, 30)), utc(2026, 9, 19, 10, 30))

    def test_a_midweek_run_is_due_after_the_next_day_s_slot(self):
        """Tuesday 22:40 UTC finish: Wednesday 22:30 is next, due Thursday 10:30."""
        self.assertEqual(due_by(utc(2026, 9, 15, 22, 40)), utc(2026, 9, 17, 10, 30))

    def test_a_run_finishing_before_that_day_s_slot_waits_for_that_slot(self):
        """A manual run on Wednesday 09:00 UTC does not count for Wednesday's
        scheduled run, which is still due that night: deadline Thursday 10:30."""
        self.assertEqual(due_by(utc(2026, 9, 16, 9, 0)), utc(2026, 9, 17, 10, 30))

    def test_a_run_finishing_exactly_on_a_slot_is_not_that_slot_s_successor(self):
        """The next slot is strictly after the run, so 22:30:00 on Monday looks
        ahead to Tuesday's."""
        self.assertEqual(due_by(utc(2026, 9, 14, 22, 30)), utc(2026, 9, 16, 10, 30))

    def test_a_weekend_run_looks_ahead_to_monday(self):
        """A manual Sunday-afternoon run: Monday's 22:30 is next, due Tuesday 10:30."""
        self.assertEqual(due_by(utc(2026, 9, 20, 15, 0)), utc(2026, 9, 22, 10, 30))

    def test_a_naive_time_is_refused_not_read_as_utc(self):
        """A timestamp with no zone could be anything; guessing UTC would turn a
        clock mistake into a plausible-looking deadline."""
        with self.assertRaises(ValueError):
            due_by(datetime(2026, 9, 18, 22, 33))


# ── The schedule copy in config.py ────────────────────────────────────────────

class ScheduleMatchesWorkflowTests(unittest.TestCase):
    def test_config_names_the_same_slot_as_the_workflows_cron_line(self):
        """`config.py` is a second copy of the cron line. If someone moves the
        cron without moving it, the header would judge the data against a
        schedule the job no longer keeps - so this fails instead."""
        workflow = (REPO_ROOT / ".github" / "workflows" / "fetch-daily.yml").read_text()
        match = re.search(r'cron:\s*"([^"]+)"', workflow)
        self.assertIsNotNone(match, "no cron line found in fetch-daily.yml")
        minute, hour, day_of_month, month, day_of_week = match.group(1).split()

        self.assertEqual((day_of_month, month), ("*", "*"), "only a day-of-week schedule is modelled")
        self.assertEqual(int(hour), config.FETCH_SCHEDULE_HOUR_UTC)
        self.assertEqual(int(minute), config.FETCH_SCHEDULE_MINUTE_UTC)

        # cron counts Sunday as 0 and Monday as 1; Python's Monday is 0. Only
        # the "a-b" range form is read, which is the form the file uses.
        first, last = (int(n) for n in day_of_week.split("-"))
        self.assertEqual(tuple(range(first - 1, last)), config.FETCH_SCHEDULE_WEEKDAYS)


# ── get_freshness ─────────────────────────────────────────────────────────────

class _FakeDb:
    """A Supabase client stand-in that answers whatever query chain it is asked
    with, and counts how many times a query actually ran."""

    def __init__(self, rows=None, error=None):
        self._rows = rows
        self._error = error
        self.reads = 0
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        return self

    def select(self, *_):
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        self.reads += 1
        if self._error is not None:
            raise self._error
        return SimpleNamespace(data=self._rows)


class _PostgrestError(Exception):
    """What supabase-py raises for a failed query: a message and a PostgREST
    `code` (PGRST205 is "table not in the schema cache")."""

    def __init__(self, code):
        super().__init__(f"postgrest error {code}")
        self.code = code


def supabase_env(configured):
    """The backend's environment as it is with, or without, Supabase configured."""
    value = "set" if configured else ""
    return patch.dict(os.environ, {"SUPABASE_URL": value, "SUPABASE_SERVICE_KEY": value})


UNKNOWN = {"finishedAt": None, "dueBy": None, "failed": None}


class GetFreshnessTests(unittest.TestCase):
    def setUp(self):
        # A fresh cache per test: the module-level singleton would carry one
        # test's answer into the next.
        cache_patch = patch("services.freshness.cache", TTLCache())
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    def _read_with(self, db, configured=True):
        with supabase_env(configured), patch(
            "services.freshness.get_client_optional", return_value=db
        ):
            return get_freshness()

    def test_answers_the_newest_run_with_its_deadline_in_utc(self):
        """A run recorded in another zone comes back as the same instant in UTC,
        with the deadline worked from the next slot: Friday's 22:30 slot is
        already past, so Monday's, plus 12h."""
        db = _FakeDb(rows=[{"finished_at": "2026-09-19T02:28:10.12345+02:00", "failed": 3}])

        self.assertEqual(
            self._read_with(db),
            {
                "finishedAt": "2026-09-19T00:28:10.123450+00:00",
                "dueBy": "2026-09-22T10:30:00+00:00",
                "failed": 3,
            },
        )
        self.assertEqual(db.tables, ["fetch_run"])

    def test_a_run_with_nothing_failed_reports_zero_not_null(self):
        """Zero failures is a finding; null means there is no run to describe."""
        db = _FakeDb(rows=[{"finished_at": "2026-09-18T22:33:00+00:00", "failed": 0}])

        self.assertEqual(self._read_with(db)["failed"], 0)

    def test_no_supabase_configured_is_unknown_not_an_error(self):
        """A local run with no backend/.env is the deliberate degraded mode; it
        must answer, all null, rather than raise."""
        self.assertEqual(self._read_with(None, configured=False), UNKNOWN)

    def test_configured_but_no_client_could_be_built_is_data_unavailable(self):
        """`get_client_optional` returns None for a cold process whose DNS or TLS
        is not ready as well as for a missing config. With the credentials set it
        is the blip, not the absence: a permanent 200 here would leave the header
        on unknown for the whole session, so it must be the retried 503."""
        with self.assertRaises(DataUnavailable):
            self._read_with(None, configured=True)

    def test_a_table_the_migration_has_not_created_yet_is_unknown_not_a_retry_storm(self):
        """The backend can be deployed before sql/005 is applied. PostgREST says
        the table is not in its schema cache; that will not change by asking
        again, so it is an absence - all null - and not a 503 the frontend would
        retry on a backoff, on every page load, until someone runs the migration."""
        for code in ("PGRST205", "42P01"):
            with self.subTest(code):
                db = _FakeDb(error=_PostgrestError(code))

                self.assertEqual(self._read_with(db), UNKNOWN)

    def test_any_other_query_error_is_still_data_unavailable(self):
        with self.assertRaises(DataUnavailable):
            self._read_with(_FakeDb(error=_PostgrestError("PGRST301")))

    def test_nothing_recorded_yet_is_unknown_not_an_error(self):
        """Right after the migration, before the first run has written a row."""
        self.assertEqual(self._read_with(_FakeDb(rows=[])), UNKNOWN)

    def test_a_database_that_cannot_be_read_is_data_unavailable(self):
        """A fact about right now, not about the record: the edge must be able
        to answer 503, so it is raised rather than folded into unknown."""
        with self.assertRaises(DataUnavailable):
            self._read_with(_FakeDb(error=RuntimeError("connection reset")))

    def test_a_found_run_is_served_from_cache_within_the_ttl(self):
        db = _FakeDb(rows=[{"finished_at": "2026-09-18T22:33:00+00:00", "failed": 0}])

        first = self._read_with(db)
        second = self._read_with(db)

        self.assertEqual(first, second)
        self.assertEqual(db.reads, 1)

    def test_a_failure_is_not_cached(self):
        """The next request retries the database instead of inheriting the outage."""
        broken = _FakeDb(error=RuntimeError("connection reset"))
        healthy = _FakeDb(rows=[{"finished_at": "2026-09-18T22:33:00+00:00", "failed": 0}])

        with self.assertRaises(DataUnavailable):
            self._read_with(broken)

        self.assertEqual(self._read_with(healthy)["failed"], 0)

    def test_an_absent_answer_is_not_cached(self):
        """An empty table is about to get its first row, and a missing table is
        about to be created; remembering either for 15 minutes would pin the
        header on unknown after the fact changed."""
        db = _FakeDb(rows=[{"finished_at": "2026-09-18T22:33:00+00:00", "failed": 0}])

        self.assertEqual(self._read_with(_FakeDb(rows=[])), UNKNOWN)
        self.assertEqual(self._read_with(_FakeDb(error=_PostgrestError("PGRST205"))), UNKNOWN)
        self.assertEqual(self._read_with(db)["failed"], 0)


# ── GET /api/freshness ────────────────────────────────────────────────────────

class FreshnessRouteTests(unittest.TestCase):
    def setUp(self):
        cache_patch = patch("services.freshness.cache", TTLCache())
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    def _get_with(self, db, configured=True):
        with supabase_env(configured), patch(
            "services.freshness.get_client_optional", return_value=db
        ):
            return client.get("/api/freshness")

    def test_answers_the_newest_run(self):
        db = _FakeDb(rows=[{"finished_at": "2026-09-18T22:33:00+00:00", "failed": 2}])

        response = self._get_with(db)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "finishedAt": "2026-09-18T22:33:00+00:00",
                "dueBy": "2026-09-22T10:30:00+00:00",
                "failed": 2,
            },
        )

    def test_nothing_to_report_is_a_200_of_nulls(self):
        """A permanent condition, not a blip: a 503 here would have the frontend
        retry, on a schedule, something that will never change on its own."""
        cases = (
            ("no supabase", None, False),
            ("no run yet", _FakeDb(rows=[]), True),
            ("table not created yet", _FakeDb(error=_PostgrestError("PGRST205")), True),
        )
        for label, db, configured in cases:
            with self.subTest(label):
                response = self._get_with(db, configured)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), UNKNOWN)

    def test_an_unreadable_database_is_a_503_with_retry_after_never_a_500(self):
        for label, db in (
            ("query failed", _FakeDb(error=RuntimeError("connection reset"))),
            ("no client could be built", None),
        ):
            with self.subTest(label):
                response = self._get_with(db, configured=True)

                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers["Retry-After"], "3")


if __name__ == "__main__":
    unittest.main()
