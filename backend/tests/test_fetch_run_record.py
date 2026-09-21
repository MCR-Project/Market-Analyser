"""
Tests for the run record `scripts/fetch_daily.py` writes about itself (issue
#154, docs/adr/0003-the-daily-job-records-its-own-runs.md) - what the header's
Freshness is read from.

The seam is `main()`, the job's entry point, because what matters is the
behaviour of a whole run: when the row is written relative to the rest of the
job, what it counts, and what a run that does not finish leaves behind. Nothing
here touches the network or Supabase - every reader the job calls is patched,
and the client is a fake that logs each write in order, so "before compaction"
is an assertion about the log rather than about the code's layout.

The rules under test, each written down in the ADR:

  - one row per run, `failed` only: `finished_at` is stamped by the database
    (its column default), not by the runner's clock;
  - written right after the price sync and before compaction, which only tidies
    storage - so a compaction failure is neither hidden behind a fresh fetch nor
    counted as data that is old;
  - `failed` counts ids the run could not refresh (ETF sync, the risk-free rate,
    prices, metadata) and not compaction failures;
  - the early "no tickers to sync" exit is a finished run and writes one too;
  - a run that crashes before the write leaves no row, and so does one whose own
    write fails - the second still finishes compaction and exits 1, so the Action
    goes red.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import fetch_daily


class _Table:
    """One `client.table(...)` builder: remembers the calls chained on it and
    acts on them when `.execute()` runs."""

    def __init__(self, client, name):
        self._client = client
        self._name = name
        self._calls = []

    def __getattr__(self, method):
        def call(*args, **kwargs):
            self._calls.append((method, args, kwargs))
            return self
        return call

    def execute(self):
        self._client.execute(self._name, self._calls)
        return SimpleNamespace(data=[])


class _FakeClient:
    def __init__(self, log, record_error=None, prices_error=None):
        self._log = log
        self._record_error = record_error
        self._prices_error = prices_error

    def table(self, name):
        return _Table(self, name)

    def execute(self, table, calls):
        methods = [method for method, _, _ in calls]
        if table == "fetch_run" and "insert" in methods:
            if self._record_error is not None:
                raise self._record_error
            payload = next(args[0] for method, args, _ in calls if method == "insert")
            self._log.append(("record", payload))
        elif table == "prices" and "upsert" in methods and self._prices_error is not None:
            raise self._prices_error


def _ticker(ticker_id):
    return {"id": ticker_id, "last_fetch": "2026-09-18", "active": True}


def run_job(
    tickers=("AAPL",),
    etf_failures=(),
    rate_synced=True,
    failing_prices=(),
    failing_metadata=(),
    failing_compaction=(),
    record_error=None,
    prices_error=None,
):
    """Run `fetch_daily.main()` against fakes. Returns (log, exit_code, error):
    the ordered log of record writes and compactions, the code `sys.exit` was
    called with (None if it returned normally), and an exception that escaped."""
    log = []
    client = _FakeClient(log, record_error=record_error, prices_error=prices_error)

    def fetch_ticker_rows(ticker_id, period):
        if ticker_id in failing_prices:
            raise RuntimeError("upstream said no")
        return [{"ticker": ticker_id, "date": "2026-09-18", "close": 1.0}], [], []

    def stock_info(ticker_id):
        if ticker_id in failing_metadata:
            raise RuntimeError("no info")
        return {
            "sector": "TECH", "marketCap": 1, "currency": "USD",
            "exchange": "NMS", "logo": None, "website": None,
        }

    def compact(_client, ticker_id, _today):
        log.append(("compact", ticker_id))
        if ticker_id in failing_compaction:
            raise RuntimeError("compaction died")
        return 0, 0, 0, 0

    patches = [
        patch.object(fetch_daily, "get_client", return_value=client),
        patch.object(fetch_daily, "sync_risk_free_rate", return_value=rate_synced),
        patch.object(fetch_daily, "paginated_select", return_value=[_ticker(t) for t in tickers]),
        patch.object(fetch_daily, "sync_etfs", return_value=list(etf_failures)),
        patch.object(fetch_daily, "fetch_ticker_rows", side_effect=fetch_ticker_rows),
        patch.object(fetch_daily, "_get_stock_info_live", side_effect=stock_info),
        patch.object(fetch_daily, "compact_ticker", side_effect=compact),
    ]
    exit_code, error = None, None
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
        for p in patches:
            stack.enter_context(p)
        try:
            fetch_daily.main()
        except SystemExit as exc:
            exit_code = exc.code
        except Exception as exc:  # a crash: reported, not raised, so the log can be read
            error = exc
    return log, exit_code, error


def records(log):
    return [entry for entry in log if entry[0] == "record"]


class RunRecordTests(unittest.TestCase):
    def test_a_clean_run_records_zero_failures_before_compaction(self):
        log, exit_code, error = run_job(tickers=("AAPL", "MSFT"))

        self.assertIsNone(error)
        self.assertIsNone(exit_code)
        self.assertEqual(
            log,
            [("record", {"failed": 0}), ("compact", "AAPL"), ("compact", "MSFT")],
        )

    def test_a_run_that_finishes_with_failures_records_how_many_and_exits_red(self):
        """Four ids could not be refreshed: an ETF (SMH), the risk-free rate,
        BAD's prices and AAPL's metadata. MSFT failing to compact leaves the data
        exactly as fresh as it was, so it is not one of them."""
        log, exit_code, error = run_job(
            tickers=("AAPL", "BAD", "MSFT"),
            etf_failures=("SMH",),
            rate_synced=False,
            failing_prices=("BAD",),
            failing_metadata=("AAPL",),
            failing_compaction=("MSFT",),
        )

        self.assertIsNone(error)
        self.assertEqual(exit_code, 1)
        self.assertEqual(records(log), [("record", {"failed": 4})])

    def test_the_row_is_written_before_any_compaction_starts(self):
        log, _, _ = run_job(tickers=("AAPL", "MSFT"), failing_compaction=("AAPL",))

        self.assertEqual(log[0][0], "record")
        self.assertEqual([entry[0] for entry in log[1:]], ["compact", "compact"])

    def test_a_job_with_nothing_to_sync_still_finished_and_records_it(self):
        log, exit_code, error = run_job(tickers=())

        self.assertIsNone(error)
        self.assertIsNone(exit_code)
        self.assertEqual(log, [("record", {"failed": 0})])

    def test_a_job_with_nothing_to_sync_records_its_failures_before_exiting_red(self):
        log, exit_code, _ = run_job(tickers=(), etf_failures=("SMH",), rate_synced=False)

        self.assertEqual(exit_code, 1)
        self.assertEqual(log, [("record", {"failed": 2})])

    def test_a_run_that_crashes_before_the_write_leaves_no_row(self):
        """An uncaught error mid-sync. A row here would claim a finish time for a
        run that did not finish - the false comfort the record exists to remove."""
        log, _, error = run_job(prices_error=RuntimeError("supabase dropped the connection"))

        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(records(log), [])

    def test_a_write_that_fails_leaves_no_row_but_the_job_carries_on_and_exits_red(self):
        log, exit_code, error = run_job(
            tickers=("AAPL", "MSFT"), record_error=RuntimeError("supabase dropped the connection")
        )

        self.assertIsNone(error)
        self.assertEqual(exit_code, 1)
        self.assertEqual(records(log), [])
        self.assertEqual(log, [("compact", "AAPL"), ("compact", "MSFT")])


if __name__ == "__main__":
    unittest.main()
