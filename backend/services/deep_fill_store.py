"""
What a Deep-fill holds in memory (issue #171, docs/adr/0006-deep-fill-writes-nothing-to-the-database.md).

Two kinds of thing, deliberately kept apart:

- **A ticker's data** - one year of adjusted daily OHLC, volume and the dividends
  paid in it - keyed by symbol, with the time it was fetched. A ticker expires
  `DEEP_FILL_TTL_SECONDS` after *it* was fetched, whatever fund asked for it, so a
  second fund that shares tickers with the first reuses them, and a cancelled job
  leaves what it fetched behind for the next press to resume from.
- **A fund's result** - which Untracked holdings it has (and their weights, taken
  when the job started, so reading the fund never needs the database again), which
  of them have data and which failed and why, and what was derived from them once
  (the correlation matrix, and the compact copy of it a Full view serves - issue #173).
  A fund is *deep-filled* exactly while a result for it
  exists. It expires when the oldest ticker it was built from does, and at most
  `DEEP_FILL_MAX_FUNDS` results are held: the one finished longest ago goes first,
  taking with it the tickers no remaining result uses.

This module is the half that `market_data` reads, so it imports nothing from it
(the job that fills it, `deep_fill.py`, imports both). It does no I/O at all, and
nothing here ever reaches the database - the whole point of the ADR.

Expiry is checked on every read rather than by a timer: an expired entry is
simply not there, so no reader can be handed a figure past its lifetime, and
"after the TTL every read returns exactly the pre-Deep-fill answer" is true by
construction rather than by a sweep that might not have run yet.

Single-process and in-memory, like `services/cache.py`: a restart loses it all,
which the ADR accepts. Every method takes the one lock; nothing is held across a
network call.
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from config import deep_fill_max_funds, deep_fill_ttl_seconds

# What a Deep-fill fetches: one year of daily history. A window that reaches
# further back than this cannot be answered for the tail (see `frames`).
FETCHED_DAYS = 365

WINDOW_REASON = (
    "a Deep-fill fetches one year of history, and this window reaches further back"
)

# A function, not `time.time` bound directly, so a test replaces what the store
# thinks the time is without touching the clock every other module reads.
_now = time.time


def iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class TickerData:
    """One Untracked ticker's fetched history. `frame` has a tz-naive daily
    DatetimeIndex and Open/High/Low/Close/Volume columns, adjusted for splits and
    dividends exactly as `prices` is (`auto_adjust=True`, invariant 2) - never
    one row per week or month, so unlike a `prices` row a row here is one trading
    day. `dividends` are the declared, unadjusted cash amounts, oldest first."""

    frame: pd.DataFrame
    dividends: list[tuple[str, float]]
    fetched_at: float


@dataclass
class FundResult:
    etf_id: str
    as_of: float
    expires_at: float
    tail: list[list]                   # [[ticker, weight%], ...] - every Untracked holding
    failures: dict[str, str]           # ticker -> why it has no data
    derived: dict = field(default_factory=dict)


class DeepFillStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._tickers: dict[str, TickerData] = {}
        self._funds: dict[str, FundResult] = {}

    # ── Expiry ────────────────────────────────────────────────────────────────

    def _purge(self) -> None:
        now = _now()
        ttl = deep_fill_ttl_seconds()
        for symbol in [s for s, d in self._tickers.items() if d.fetched_at + ttl <= now]:
            del self._tickers[symbol]
        for etf_id in [e for e, r in self._funds.items() if r.expires_at <= now]:
            del self._funds[etf_id]

    # ── Tickers ───────────────────────────────────────────────────────────────

    def put_ticker(self, symbol: str, data: TickerData) -> None:
        with self._lock:
            self._tickers[symbol] = data

    def ticker(self, symbol: str) -> TickerData | None:
        with self._lock:
            self._purge()
            return self._tickers.get(symbol)

    def missing(self, symbols: list[str]) -> list[str]:
        """The symbols with no unexpired data, in the order given."""
        with self._lock:
            self._purge()
            return [s for s in symbols if s not in self._tickers]

    # ── Funds ─────────────────────────────────────────────────────────────────

    def put_fund(self, result: FundResult) -> None:
        """Hold a finished fund, evicting the one finished longest ago for each
        fund over `DEEP_FILL_MAX_FUNDS`, and the tickers only that one used."""
        with self._lock:
            self._funds.pop(result.etf_id, None)
            self._funds[result.etf_id] = result
            self._purge()
            limit = deep_fill_max_funds()
            while len(self._funds) > limit:
                oldest = min(self._funds.values(), key=lambda r: r.as_of)
                del self._funds[oldest.etf_id]
                still_used = {t for r in self._funds.values() for t, _ in r.tail}
                for symbol, _ in oldest.tail:
                    if symbol not in still_used:
                        self._tickers.pop(symbol, None)

    def fund(self, etf_id: str) -> FundResult | None:
        with self._lock:
            self._purge()
            return self._funds.get(etf_id)

    def describe(self, etf_id: str) -> dict | None:
        """What a response says about a deep-filled fund: `asOf`, `expiresAt` and
        which of its holdings are Untracked. None when the fund is not deep-filled,
        so a response only grows these fields while they are true."""
        result = self.fund(etf_id)
        if result is None:
            return None
        return {
            "asOf": iso(result.as_of),
            "expiresAt": iso(result.expires_at),
            "untracked": [ticker for ticker, _ in result.tail],
        }

    # ── Reads ─────────────────────────────────────────────────────────────────
    #
    # Everything a reader needs to treat a deep-filled fund's tail like prices it
    # has: which tickers are in a held tail, their series over a window, their
    # dividends, and, for the ones it cannot give, why.

    def tail_tickers(self) -> set[str]:
        """Every ticker in the tail of a fund that is deep-filled right now. Not
        every ticker with data - a cancelled job leaves some behind, and a fund
        that is not deep-filled must keep reading as pruned."""
        with self._lock:
            self._purge()
            return {ticker for r in self._funds.values() for ticker, _ in r.tail}

    def frames(self, tickers: list[str], lower: str | None, upper: str | None):
        """`(closes, volume, excluded)` for the tail tickers among `tickers`, over
        the window [lower, upper] (ISO dates, either may be None).

        `closes` and `volume` are date x ticker frames of the tickers that can
        answer; `excluded` is `{ticker: reason}` for the rest. A ticker is excluded
        when the job has no data for it (it failed, or expired), or when the window
        reaches further back than the year it fetched: `lower` of None means the
        whole history there is, which a year is not. Never a shorter series passed
        off as the one asked for - the reader would compute a figure over a window
        nobody chose (invariant 7)."""
        with self._lock:
            self._purge()
            failures = self._failures_locked()
            chosen = {}
            excluded = {}
            for ticker in tickers:
                data = self._tickers.get(ticker)
                if data is None:
                    excluded[ticker] = _unfetched(failures.get(ticker))
                elif not _covers(data, lower):
                    excluded[ticker] = WINDOW_REASON
                else:
                    chosen[ticker] = data.frame.loc[lower:upper]
        closes = pd.DataFrame({t: f["Close"] for t, f in chosen.items()})
        volume = pd.DataFrame({t: f["Volume"] for t, f in chosen.items()})
        return closes, volume, excluded

    def explain(self, tickers: list[str], lower: str | None) -> dict[str, str]:
        """`{ticker: reason}` for the tickers that cannot answer a window opening
        at `lower` - the same test `frames` applies, without building a frame."""
        with self._lock:
            self._purge()
            failures = self._failures_locked()
            reasons = {}
            for ticker in tickers:
                data = self._tickers.get(ticker)
                if data is None:
                    reasons[ticker] = _unfetched(failures.get(ticker))
                elif not _covers(data, lower):
                    reasons[ticker] = WINDOW_REASON
            return reasons

    def dividends(self, tickers: list[str]) -> dict[str, list[tuple[str, float]]]:
        """The dividends fetched for each of `tickers` that has data - an empty
        list is a real answer (a year of data and none paid), a ticker with no
        data is simply absent."""
        with self._lock:
            self._purge()
            return {t: list(self._tickers[t].dividends) for t in tickers if t in self._tickers}

    def _failures_locked(self) -> dict[str, str]:
        return {t: reason for r in self._funds.values() for t, reason in r.failures.items()}

    # ── Derived results ───────────────────────────────────────────────────────

    def attach_derived(self, etf_id: str, name: str, value: dict) -> None:
        with self._lock:
            result = self._funds.get(etf_id)
            if result is not None:
                result.derived[name] = value

    def full_view(self, etf_id: str) -> dict | None:
        """What a Full view is drawn from, or None when there is none to draw: the
        fund is not deep-filled (never, expired, or its job is still running - a
        partial tail has no result yet), or the job finished without being able to
        derive one. `asOf` and `expiresAt` are the Deep-fill's own, so the page says
        exactly what `GET /api/deep-fill/{id}` does. A copy at the top level, since
        a route may add to what it gets back."""
        with self._lock:
            self._purge()
            result = self._funds.get(etf_id)
            held = result.derived.get("fullView") if result is not None else None
            if held is None:
                return None
            return {"etfId": etf_id, "asOf": iso(result.as_of), "expiresAt": iso(result.expires_at), **held}

    def derived_correlation(self, tickers: list[str], period: str) -> dict | None:
        """The correlation matrix a Deep-fill finished with, if `tickers` in this
        order over this period is exactly what it was computed for. A copy, because
        a route adds fields to what it gets back and the stored result is the one
        a Full view says it was drawn from."""
        with self._lock:
            self._purge()
            for result in self._funds.values():
                held = result.derived.get("correlation")
                if held and held["period"] == period and held["tickers"] == list(tickers):
                    return dict(held["value"])
        return None


def _unfetched(failure: str | None) -> str:
    if failure:
        return f"the Deep-fill could not fetch it: {failure}"
    return "the Deep-fill holds no data for it"


def _covers(data: TickerData, lower: str | None) -> bool:
    """Whether what was fetched reaches back to `lower`. The fetch asked for a
    year ending the day it ran, so it covers a window opening on or after that day
    last year; an open-ended window (`lower` is None, "max") is never covered."""
    if lower is None:
        return False
    start = date.fromtimestamp(data.fetched_at) - timedelta(days=FETCHED_DAYS)
    return lower >= start.isoformat()


# The one store every reader and the job share. Tests replace this name with a
# fresh instance, the way they replace `services.cache.cache`.
store = DeepFillStore()
