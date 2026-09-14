"""
Tests for reaching prices, volume, stock metadata and dividends from
measurement inputs (issue #102).

Three getters, three different shapes of the same underlying rule -
"never call services.market_data directly, and never guess at an absence
this codebase already knows how to name":

  - `price_frame` bulk-reads close prices, and volume wherever the
    database can answer for it, for a whole fund's holdings in one query
    - and shares that read with `compute_correlation_matrix` when the two
    ask for the same tickers and window, rather than each issuing its
    own. `PriceFrameDbTests` and `PriceFrameBundleCachingTests` pin down
    the shared read at the services layer; `GetPriceFrameShapeTests` and
    `PriceFrameInputGetterTests` pin down what a measurement actually
    receives.

  - `stock_info` is a thin per-ticker loop over the already-cached
    `services.market_data.get_stock_info` - there is no bulk read to
    share here, unlike price_frame's.

  - `dividend_events` wraps `get_dividends` together with
    `tracked_tickers` so a caller can tell "tracked, paid nothing" from
    "no record here" without having to remember to ask both itself - the
    same distinction `services/portfolio.py` already makes for the
    simulator.

Run with:   pytest   (from the repo root; also runnable standalone via
            python -m unittest discover -s tests, from backend/)
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from config import CORRELATION_INTERVAL, CORRELATION_PERIOD
from measurements.examples import MAX_LIST_ITEMS, truncate
from measurements.inputs import INPUT_REGISTRY, dividend_events, price_frame, stock_info
from services.cache import TTLCache
from services.market_data import (
    _price_frame_bundle,
    _price_frame_db,
    compute_correlation_matrix,
    get_price_frame,
)


# ── Fakes for the Supabase seam (same shape as test_price_windows.py's) ──────

class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._start = 0
        self._end = None

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def eq(self, column, value):
        self._rows = [r for r in self._rows if r[column] == value]
        return self

    def in_(self, column, values):
        self._rows = [r for r in self._rows if r[column] in values]
        return self

    def gte(self, column, value):
        self._rows = [r for r in self._rows if r[column] >= value]
        return self

    def lte(self, column, value):
        self._rows = [r for r in self._rows if r[column] <= value]
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows[self._start:self._end + 1])


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def table(self, name):
        query = _FakeQuery(sorted(self._rows, key=lambda r: (r["date"], r["granularity"])))
        self.queries.append(query)
        return query


def _price_rows():
    return [
        {"ticker": "NVDA", "date": "2024-06-06", "close": 120.0, "volume": 1_000, "granularity": "D"},
        {"ticker": "NVDA", "date": "2024-06-07", "close": 121.0, "volume": 1_100, "granularity": "D"},
    ]


# ── _price_frame_db: the widened bulk read ────────────────────────────────────

class PriceFrameDbTests(unittest.TestCase):
    def test_pivots_close_volume_and_granularity(self):
        db = _FakeClient(_price_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            result = _price_frame_db(["NVDA"], None, start="2024-06-01", end="2024-06-30", min_tickers=1)

        self.assertEqual(list(result["close"]["NVDA"]), [120.0, 121.0])
        self.assertEqual(list(result["volume"]["NVDA"]), [1_000, 1_100])
        self.assertEqual(list(result["granularity"]["NVDA"]), ["D", "D"])

    def test_one_query_for_the_whole_basket(self):
        """The acceptance criterion at the query layer: however many
        tickers are asked for, exactly one `prices` read answers them."""
        db = _FakeClient(_price_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            _price_frame_db(["NVDA"], None, start="2024-06-01", end="2024-06-30", min_tickers=1)

        self.assertEqual(len(db.queries), 1)

    def test_min_tickers_gates_a_partial_answer_the_same_as_closes_db(self):
        db = _FakeClient(_price_rows())
        with patch("services.market_data.get_client_optional", return_value=db):
            too_few = _price_frame_db(["NVDA", "GHOST"], None, start="2024-06-01", end="2024-06-30", min_tickers=2)
            enough = _price_frame_db(["NVDA", "GHOST"], None, start="2024-06-01", end="2024-06-30", min_tickers=1)

        self.assertIsNone(too_few)
        self.assertEqual(list(enough["close"].columns), ["NVDA"])


# ── _price_frame_bundle: the shared, cached read ──────────────────────────────

class PriceFrameBundleCachingTests(unittest.TestCase):
    def test_the_same_request_is_served_from_cache(self):
        bundle = {
            "close": pd.DataFrame({"NVDA": [120.0]}, index=pd.to_datetime(["2024-06-06"])),
            "volume": pd.DataFrame({"NVDA": [1_000]}, index=pd.to_datetime(["2024-06-06"])),
            "granularity": pd.DataFrame({"NVDA": ["D"]}, index=pd.to_datetime(["2024-06-06"])),
        }
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._price_frame_db", return_value=bundle) as mock_db:
            _price_frame_bundle(["NVDA"], "1y", "1d", None, None, min_tickers=1)
            _price_frame_bundle(["NVDA"], "1y", "1d", None, None, min_tickers=1)

        mock_db.assert_called_once()

    def test_min_tickers_is_not_part_of_the_cache_key(self):
        """price_frame's own default (1) and correlation's (2) must not
        stop the two from sharing an entry - see _price_frame_bundle's
        docstring for why min_tickers is deliberately excluded from the
        key rather than making them independent reads."""
        bundle = {
            "close": pd.DataFrame({"NVDA": [120.0], "MSFT": [300.0]}, index=pd.to_datetime(["2024-06-06"])),
            "volume": None,
            "granularity": None,
        }
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._price_frame_db", return_value=bundle) as mock_db:
            _price_frame_bundle(["NVDA", "MSFT"], "1y", "1d", None, None, min_tickers=1)
            _price_frame_bundle(["NVDA", "MSFT"], "1y", "1d", None, None, min_tickers=2)

        mock_db.assert_called_once()

    def test_a_different_window_is_a_different_entry(self):
        bundle = {
            "close": pd.DataFrame({"NVDA": [120.0]}, index=pd.to_datetime(["2024-06-06"])),
            "volume": None, "granularity": None,
        }
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._price_frame_db", return_value=bundle) as mock_db:
            _price_frame_bundle(["NVDA"], "1y", "1d", None, None, min_tickers=1)
            _price_frame_bundle(["NVDA"], "5y", "1d", None, None, min_tickers=1)

        self.assertEqual(mock_db.call_count, 2)

    def test_a_ticker_merged_in_live_has_no_volume(self):
        """No live fallback for volume (issue #102): a ticker the database
        has no `prices` rows for at all - every ETF, and anything
        resolved outside the tracked universe - gets real closes from the
        live merge but volume=None throughout, never an invented number."""
        db_bundle = {
            "close": pd.DataFrame({"TXN": [10.0]}, index=pd.to_datetime(["2024-06-06"])),
            "volume": pd.DataFrame({"TXN": [500]}, index=pd.to_datetime(["2024-06-06"])),
            "granularity": pd.DataFrame({"TXN": ["D"]}, index=pd.to_datetime(["2024-06-06"])),
        }
        live_close = pd.DataFrame({"SPY": [400.0]}, index=pd.to_datetime(["2024-06-06"]))
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._price_frame_db", return_value=db_bundle), \
             patch("services.market_data._closes_live", return_value=live_close):
            bundle = _price_frame_bundle(["TXN", "SPY"], "1y", "1d", None, None, min_tickers=1)

        self.assertIn("SPY", bundle["close"].columns)
        self.assertNotIn("SPY", bundle["volume"].columns)
        self.assertEqual(list(bundle["volume"]["TXN"]), [500])

    def test_a_genuine_miss_is_not_cached(self):
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._price_frame_db", return_value=None), \
             patch("services.market_data._closes_live", return_value=None) as mock_live:
            first = _price_frame_bundle(["GHOST"], "1y", "1d", None, None, min_tickers=1)
            second = _price_frame_bundle(["GHOST"], "1y", "1d", None, None, min_tickers=1)

        self.assertIsNone(first["close"])
        self.assertIsNone(second["close"])
        self.assertEqual(mock_live.call_count, 2)


# ── compute_correlation_matrix shares the bundle with get_price_frame ────────

class CorrelationSharesTheBundleTests(unittest.TestCase):
    def test_a_price_frame_then_a_correlation_over_the_same_window_reads_once(self):
        """The acceptance criterion, end to end: price_frame's own default
        window is CORRELATION_PERIOD specifically so this holds."""
        bundle = {
            "close": pd.DataFrame(
                {"NVDA": [100.0, 101.0], "MSFT": [200.0, 202.0]},
                index=pd.to_datetime(["2024-06-06", "2024-06-07"]),
            ),
            "volume": None, "granularity": None,
        }
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._price_frame_db", return_value=bundle) as mock_db:
            get_price_frame(["NVDA", "MSFT"], period=CORRELATION_PERIOD)
            compute_correlation_matrix(["NVDA", "MSFT"], period=CORRELATION_PERIOD, interval=CORRELATION_INTERVAL)

        mock_db.assert_called_once()


# ── get_price_frame: the JSON-native shape ────────────────────────────────────

class GetPriceFrameShapeTests(unittest.TestCase):
    def test_closes_and_volume_for_a_tracked_ticker(self):
        db = _FakeClient(_price_rows())
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data.get_client_optional", return_value=db):
            result = get_price_frame(["NVDA"], start="2024-06-01", end="2024-06-30", min_tickers=1)

        self.assertEqual(result["NVDA"]["closes"], [["2024-06-06", 120.0], ["2024-06-07", 121.0]])
        self.assertEqual(
            result["NVDA"]["volume"],
            [
                {"date": "2024-06-06", "volume": 1_000, "granularity": "D"},
                {"date": "2024-06-07", "volume": 1_100, "granularity": "D"},
            ],
        )

    def test_volume_is_null_not_zero_for_an_etf_holding(self):
        db_bundle = {
            "close": pd.DataFrame({"TXN": [10.0]}, index=pd.to_datetime(["2024-06-06"])),
            "volume": pd.DataFrame({"TXN": [500]}, index=pd.to_datetime(["2024-06-06"])),
            "granularity": pd.DataFrame({"TXN": ["D"]}, index=pd.to_datetime(["2024-06-06"])),
        }
        live_close = pd.DataFrame({"SPY": [400.0]}, index=pd.to_datetime(["2024-06-06"]))
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._price_frame_db", return_value=db_bundle), \
             patch("services.market_data._closes_live", return_value=live_close):
            result = get_price_frame(["TXN", "SPY"], min_tickers=1)

        self.assertIsNone(result["SPY"]["volume"])
        self.assertIsNotNone(result["TXN"]["volume"])

    def test_a_ticker_with_no_data_anywhere_is_absent(self):
        with patch("services.market_data.cache", TTLCache()), \
             patch("services.market_data._price_frame_db", return_value=None), \
             patch("services.market_data._closes_live", return_value=None):
            result = get_price_frame(["GHOST"], min_tickers=1)

        self.assertEqual(result, {})


# ── measurements/inputs/price_frame.py ────────────────────────────────────────

class PriceFrameInputGetterTests(unittest.TestCase):
    def test_default_period_matches_correlations_own(self):
        """So a doc page or measurement reading both price_frame and
        correlation_matrix for the same fund ends up asking for literally
        the same cache key (see _price_frame_bundle)."""
        self.assertEqual(price_frame.DEFAULT_PERIOD, CORRELATION_PERIOD)

    def test_volume_is_left_out_by_default(self):
        fake = {"NVDA": {"closes": [["2024-06-06", 120.0]], "volume": [{"date": "2024-06-06", "volume": 1000, "granularity": "D"}]}}
        with patch("measurements.inputs.price_frame._get_price_frame", return_value=fake):
            result = price_frame.get_price_frame(["NVDA"])

        self.assertEqual(result, {"NVDA": {"closes": [["2024-06-06", 120.0]]}})

    def test_include_volume_keeps_it(self):
        fake = {"NVDA": {"closes": [["2024-06-06", 120.0]], "volume": None}}
        with patch("measurements.inputs.price_frame._get_price_frame", return_value=fake):
            result = price_frame.get_price_frame(["NVDA"], include_volume=True)

        self.assertEqual(result, fake)

    def test_sample_is_empty_for_no_tickers(self):
        self.assertEqual(price_frame._sample("SPY", []), {})

    def test_a_worked_example_sample_survives_truncation(self):
        """examples.py's truncate() must not choke on this shape - a long
        daily series is exactly what it exists to cut down."""
        sample = {
            "NVDA": {
                "closes": [[f"2024-06-{d:02d}", 100.0 + d] for d in range(1, 20)],
                "volume": [{"date": f"2024-06-{d:02d}", "volume": d * 10, "granularity": "D"} for d in range(1, 20)],
            },
        }
        cut, dropped = truncate(sample, ["NVDA"], ["NVDA"])

        self.assertTrue(dropped)
        self.assertLessEqual(len(cut["NVDA"]["closes"]), MAX_LIST_ITEMS)
        self.assertLessEqual(len(cut["NVDA"]["volume"]), MAX_LIST_ITEMS)


# ── measurements/inputs/stock_info.py ─────────────────────────────────────────

class StockInfoInputGetterTests(unittest.TestCase):
    def test_loops_the_per_ticker_service_call(self):
        fake = {"NVDA": {"name": "NVIDIA"}, "MSFT": {"name": "Microsoft"}}
        with patch("measurements.inputs.stock_info._get_stock_info", side_effect=lambda t: fake[t]) as mock_get:
            result = stock_info.get_stock_info(["NVDA", "MSFT"])

        self.assertEqual(result, fake)
        self.assertEqual(mock_get.call_count, 2)

    def test_sample_is_empty_for_no_tickers(self):
        self.assertEqual(stock_info._sample("SPY", []), {})


# ── measurements/inputs/dividend_events.py ────────────────────────────────────

class DividendEventsInputGetterTests(unittest.TestCase):
    def test_tracked_paid_nothing_differs_from_no_record(self):
        """The whole point: two tickers that both come back with an empty
        events list must still be told apart."""
        with patch("measurements.inputs.dividend_events.get_dividends",
                    return_value={"AAPL": [("2024-03-01", 0.24)]}), \
             patch("measurements.inputs.dividend_events.tracked_tickers",
                    return_value={"AAPL", "MSFT"}):
            result = dividend_events.get_dividend_events(["AAPL", "MSFT", "SPY"])

        self.assertEqual(result["AAPL"], {"events": [["2024-03-01", 0.24]], "tracked": True})
        self.assertEqual(result["MSFT"], {"events": [], "tracked": True})
        self.assertEqual(result["SPY"], {"events": [], "tracked": False})

    def test_sample_is_empty_for_no_tickers(self):
        self.assertEqual(dividend_events._sample("SPY", []), {})


# ── Registration ───────────────────────────────────────────────────────────────

class InputRegistryTests(unittest.TestCase):
    def test_all_three_getters_are_registered(self):
        self.assertIs(INPUT_REGISTRY["price_frame"], price_frame.INPUT_SPEC)
        self.assertIs(INPUT_REGISTRY["stock_info"], stock_info.INPUT_SPEC)
        self.assertIs(INPUT_REGISTRY["dividend_events"], dividend_events.INPUT_SPEC)

    def test_each_spec_has_the_required_shape(self):
        for name in ("price_frame", "stock_info", "dividend_events"):
            with self.subTest(name=name):
                spec = INPUT_REGISTRY[name]
                self.assertIn("description", spec)
                self.assertIn("defaults", spec)
                self.assertTrue(callable(spec["sample"]))


if __name__ == "__main__":
    unittest.main()
