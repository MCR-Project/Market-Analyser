"""
The Deep-fill job (issue #171, docs/adr/0006-deep-fill-writes-nothing-to-the-database.md).

A Deep-fill reads a fund as its whole basket. The fund's Untracked holdings - the
~450 a fund like SPY lists but this app stores no prices for (ADR 0005) - are
fetched from yfinance on request, held in the backend's memory (`deep_fill_store`)
for `DEEP_FILL_TTL_SECONDS`, and read by everything that reads that fund until
they expire. **Nothing is written to the database**, by this module or by anything
it calls: it reads `etf_holdings` for what to fetch and `untracked_metadata` for
what the holdings are, and that is all.

It is slow - a batched download of ~450 tickers takes minutes, and a rate-limited
one longer - so it is a background job with progress, not a request:

- **One job at a time**, in one daemon thread. Pressing start for the fund that is
  running *attaches* to it (and, if a cancel was pending, withdraws it); for any
  other fund it is refused with the running job's progress (`DeepFillBusy`).
- **Batched** `yf.download(..., auto_adjust=True)`, `DEEP_FILL_BATCH_SIZE` tickers
  at a time, so the raw data in memory at once is one batch, not the whole fund.
  Adjusted on every path for the reason `prices` is (invariant 2): a raw close
  would read a split as a one-day crash.
- **Per-ticker failures are named, not fatal.** A symbol yfinance returned no
  history for is recorded with the reason and the job carries on; the fund is
  deep-filled without it and the reads say so. A *batch* that cannot be fetched at
  all - the upstream is down - is retried a few times and then ends the job as
  `failed`, keeping everything fetched so far, because those tickers are not bad,
  merely not fetched yet.
- **Cancel keeps what was fetched.** The running batch finishes (a download cannot
  be interrupted) and is kept, then the job stops. Pressing start again fetches
  only the tickers with no unexpired data - which is also how a `failed` job is
  resumed, and how a second fund that shares tickers with a first costs only the
  difference.
- **It respects the rate-limit cooldown** `market_data` keeps (issue #92): every
  download goes through `market_data._live`, which starts it on a 429 and refuses
  to dial out while it runs, and the job waits the cooldown out - without counting
  the wait as a failed attempt - instead of adding to the traffic that keeps the
  limit in place.

`status()` is what the frontend polls: whether the feature is enabled, how long a
result is kept (`ttlSeconds`), how many Untracked holdings the fund has and what
share of its weight they are, the job's progress as done/total with its failures
by name, and when the result was drawn and when it expires. It never raises for a fund with nothing to show - that is `idle`.

Off unless `ALLOW_DEEP_FILL` is set (`config.deep_fill_enabled`): fetching ~450
tickers is more than the live demo should be asked to do, so `start` raises
`DeepFillDisabled` and fetches nothing.
"""

import logging
import threading

import pandas as pd
import yfinance as yf

from config import (
    CORRELATION_PERIOD,
    DEEP_FILL_MAX_UNTRACKED,
    RATE_LIMIT_COOLDOWN_SECONDS,
    deep_fill_batch_size,
    deep_fill_enabled,
    deep_fill_ttl_seconds,
)
from services import deep_fill_store, full_view
from services import market_data
from services.deep_fill_store import FundResult, TickerData

log = logging.getLogger(__name__)

# How many times one batch is tried before the job gives up and ends `failed`.
BATCH_ATTEMPTS = 3

_FIELDS = ["Open", "High", "Low", "Close", "Volume"]


class DeepFillDisabled(RuntimeError):
    """`ALLOW_DEEP_FILL` is off. Mapped to a status the frontend never retries
    (routes.py): turning the feature on is a deployment decision, not a thing
    asking again can change."""


class DeepFillBusy(RuntimeError):
    """Another fund's job is running. `status` is that job's progress, which the
    route returns alongside the refusal so the caller can say what it is waiting on."""

    def __init__(self, status: dict):
        super().__init__("a Deep-fill is already running for another fund")
        self.status = status


class _Cancelled(Exception):
    """The job was cancelled while it was waiting (out a cooldown, or a retry)."""


class _GiveUp(RuntimeError):
    """A batch could not be fetched after every attempt; ends the job `failed`."""


def _wait(event: threading.Event, seconds: float) -> bool:
    """Sleep up to `seconds`, waking at once if `event` is set. True if it was.
    A module function so a test replaces it rather than actually waiting."""
    return event.wait(seconds)


class _Job:
    def __init__(self, etf_id: str, tail: list[list]):
        self.etf_id = etf_id
        self.tail = tail
        self.state = "running"          # running | done | cancelled | failed
        self.done = 0
        self.failures: dict[str, str] = {}
        self.error: str | None = None
        self.cancel = threading.Event()

    def progress(self) -> dict:
        return {
            "done": self.done,
            "total": len(self.tail),
            "failed": [{"ticker": t, "reason": r} for t, r in self.failures.items()],
        }


class DeepFill:
    def __init__(self):
        self._lock = threading.RLock()
        self._job: _Job | None = None
        self._thread: threading.Thread | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    def join(self, timeout: float | None = None) -> None:
        """Wait for the running job's thread to end. For tests and shutdown."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def start(self, etf_id: str) -> dict:
        """Start a Deep-fill of `etf_id`, or attach to the one already running for
        it, and answer its status. Raises `DeepFillDisabled` while the feature is
        off, `DeepFillBusy` while another fund's job runs, `ValueError` for a fund
        that cannot be deep-filled (nothing Untracked in it, or too much), and
        `DataUnavailable` when the database cannot say what its Untracked holdings
        are. A fund whose result is still held is answered as `ready` and nothing
        is fetched - checked before whether another fund's job is running, since
        asking after a fund that is already done is not asking for a second job.

        The lock guards job state only. Nothing that can wait on the database or
        yfinance happens under it: the job thread takes the same lock for every
        progress update, so a slow read here would freeze the progress it reports.
        """
        if not deep_fill_enabled():
            raise DeepFillDisabled("Deep-fill is switched off on this server")

        answer, busy = self._attach_or_refuse(etf_id)
        if busy is not None:
            raise DeepFillBusy(self._render(busy["etfId"], busy))
        if answer is not None:
            return self._render(etf_id, answer)

        tail = market_data.get_untracked_holdings(etf_id)
        if not tail:
            raise ValueError(f"'{etf_id}' has no Untracked holdings to Deep-fill")
        if len(tail) > DEEP_FILL_MAX_UNTRACKED:
            raise ValueError(
                f"'{etf_id}' has {len(tail)} Untracked holdings; a Deep-fill is "
                f"limited to {DEEP_FILL_MAX_UNTRACKED} to stay inside the server's memory"
            )

        with self._lock:
            # Re-checked: another press may have started a job while the read above
            # was out.
            answer, busy = self._attach_or_refuse(etf_id)
            if answer is None and busy is None:
                job = _Job(etf_id, [list(row) for row in tail])
                self._job = job
                self._thread = threading.Thread(
                    target=self._run, args=(job, deep_fill_batch_size()),
                    name=f"deep-fill-{etf_id}", daemon=True,
                )
                self._thread.start()
                answer = self._snapshot(etf_id)
        if busy is not None:
            raise DeepFillBusy(self._render(busy["etfId"], busy))
        return self._render(etf_id, answer)

    def _attach_or_refuse(self, etf_id: str):
        """`(snapshot, None)` if the fund is already deep-filled or its own job is
        running (withdrawing a pending cancel - pressing start again is how a cancel
        is taken back), `(None, snapshot_of_the_running_job)` if another fund's is,
        and `(None, None)` when the way is clear to start one."""
        with self._lock:
            if deep_fill_store.store.fund(etf_id) is not None:
                return self._snapshot(etf_id), None
            job = self._job
            if job is not None and job.state == "running":
                if job.etf_id == etf_id:
                    job.cancel.clear()
                    return self._snapshot(etf_id), None
                return None, self._snapshot(job.etf_id)
            return None, None

    def cancel(self, etf_id: str) -> dict:
        """Ask the running job for `etf_id` to stop after the batch it is on,
        keeping everything fetched. Idempotent: with nothing running for this
        fund it only reports the status."""
        with self._lock:
            job = self._job
            if job is not None and job.state == "running" and job.etf_id == etf_id:
                job.cancel.set()
            snapshot = self._snapshot(etf_id)
        return self._render(etf_id, snapshot)

    def status(self, etf_id: str) -> dict:
        with self._lock:
            snapshot = self._snapshot(etf_id)
        return self._render(etf_id, snapshot)

    # ── Status ────────────────────────────────────────────────────────────────
    #
    # Two steps so no read waits under the lock: `_snapshot` copies the job's
    # state out (lock held, no I/O), `_render` turns it into the answer and is the
    # only part that may read the database.

    def _snapshot(self, etf_id: str) -> dict:
        job = self._job
        mine = job if job is not None and job.etf_id == etf_id else None
        result = deep_fill_store.store.fund(etf_id)
        running = mine is not None and mine.state == "running"

        if running:
            tail, state = list(mine.tail), "running"
        elif result is not None:
            tail, state = list(result.tail), "ready"
        elif mine is not None:
            tail = list(mine.tail)
            state = mine.state if mine.state in ("cancelled", "failed") else "idle"
        else:
            tail, state = None, "idle"       # unknown until the database is asked

        progress = None
        if mine is not None and (result is None or running):
            progress = mine.progress()
        elif result is not None:
            progress = {
                "done": len(result.tail),
                "total": len(result.tail),
                "failed": [{"ticker": t, "reason": r} for t, r in result.failures.items()],
            }

        other = None
        if job is not None and job.state == "running" and job.etf_id != etf_id:
            other = {"etfId": job.etf_id, "done": job.done, "total": len(job.tail)}

        return {
            "etfId": etf_id,
            "state": state,
            "tail": tail,
            "progress": progress,
            "cancelRequested": bool(running and mine.cancel.is_set()),
            "error": mine.error if mine is not None and state == "failed" else None,
            "asOf": deep_fill_store.iso(result.as_of) if result is not None else None,
            "expiresAt": deep_fill_store.iso(result.expires_at) if result is not None else None,
            "running": other,
        }

    def _render(self, etf_id: str, snapshot: dict) -> dict:
        snapshot = dict(snapshot)
        tail = snapshot.pop("tail")
        if tail is None:
            tail = market_data.get_untracked_holdings(etf_id)
        return {
            "etfId": snapshot.pop("etfId"),
            "enabled": deep_fill_enabled(),
            # How long a result is kept, known before there is one: the warning
            # dialog (issue #172) states it before anyone presses start.
            "ttlSeconds": deep_fill_ttl_seconds(),
            "state": snapshot.pop("state"),
            "untracked": self._untracked_summary(etf_id, tail),
            **snapshot,
        }

    @staticmethod
    def _untracked_summary(etf_id: str, tail: list[list]) -> dict:
        weight = round(sum(w for _, w in tail), 2)
        if not tail:
            return {"count": 0, "weight": 0.0, "weightShare": None}
        tracked, _ = market_data._base_etf_holdings(etf_id)
        whole = sum(w for _, w in tracked) + weight
        return {
            "count": len(tail),
            "weight": weight,
            "weightShare": round(weight / whole * 100, 2) if whole else None,
        }

    # ── The job ───────────────────────────────────────────────────────────────

    def _run(self, job: _Job, batch_size: int) -> None:
        store = deep_fill_store.store
        try:
            symbols = [t for t, _ in job.tail]
            todo = store.missing(symbols)
            job.done = len(symbols) - len(todo)
            # A local flag, not a second look at the event: a press of start can
            # withdraw the cancel between the loop leaving and this check, and a
            # job that stopped with most of the fund unfetched would then be
            # finished as if it had not.
            stopped = False
            for i in range(0, len(todo), batch_size):
                if job.cancel.is_set():
                    stopped = True
                    break
                chunk = todo[i:i + batch_size]
                fetched, failed = self._fetch(chunk, job)
                for symbol, data in fetched.items():
                    store.put_ticker(symbol, data)
                with self._lock:
                    job.failures.update(failed)
                    job.done += len(chunk)
            if stopped:
                with self._lock:
                    job.state = "cancelled"
                return
            self._finish(job)
        except _Cancelled:
            with self._lock:
                job.state = "cancelled"
        except _GiveUp as exc:
            with self._lock:
                job.state, job.error = "failed", str(exc)
        except Exception as exc:  # a thread has no caller to raise to
            log.exception("Deep-fill of %s crashed", job.etf_id)
            with self._lock:
                job.state, job.error = "failed", f"{type(exc).__name__}: {exc}"

    def _finish(self, job: _Job) -> None:
        store = deep_fill_store.store
        failures = dict(job.failures)
        fetched_at = []
        for symbol, _ in job.tail:
            data = store.ticker(symbol)
            if data is None:
                failures.setdefault(symbol, "its data expired before the Deep-fill finished")
            else:
                fetched_at.append(data.fetched_at)
                failures.pop(symbol, None)
        if not fetched_at:
            raise _GiveUp("no Untracked holding could be fetched")

        result = FundResult(
            etf_id=job.etf_id,
            as_of=deep_fill_store._now(),
            expires_at=min(fetched_at) + deep_fill_ttl_seconds(),
            tail=job.tail,
            failures=failures,
        )
        store.put_fund(result)
        self._derive(job.etf_id)
        with self._lock:
            job.failures = failures
            job.state = "done"

    def _derive(self, etf_id: str) -> None:
        """Compute, once, what a Full view is drawn from and hold it with the
        result: the fund's correlation matrix and clusters over the whole basket,
        tracked and tail together. The result is already registered, so the reads
        this makes see the tail exactly as every later one will. If the tracked
        half cannot be read right now nothing is held and each read computes it for
        itself, as it would without a Deep-fill - the fund is still deep-filled.

        The Fund Index has no entry here: its inputs are the per-ticker series the
        store already holds, and `get_fund_index` builds it from them on read.
        """
        holdings, _ = market_data.get_etf_holdings(etf_id)
        tickers = [ticker for ticker, _ in holdings]
        try:
            matrix = market_data.compute_correlation_matrix(tickers, period=CORRELATION_PERIOD)
        except market_data.DataUnavailable:
            return
        if matrix.get("matrix"):
            deep_fill_store.store.attach_derived(
                etf_id, "correlation",
                {"tickers": tickers, "period": CORRELATION_PERIOD, "value": matrix},
            )
            # What the Full view (issue #173) is drawn from, built here so opening
            # it reads and computes nothing.
            result = deep_fill_store.store.fund(etf_id)
            try:
                payload = full_view.build(
                    holdings, matrix, result.failures if result is not None else {}, CORRELATION_PERIOD
                )
            except Exception:
                # The fund is already deep-filled and every read has its matrix; only
                # the Full view is lost. Letting this escape would end a finished job as
                # "crashed" over a page nobody has opened yet.
                log.exception("Deep-fill of %s finished but its Full view could not be built", etf_id)
                return
            deep_fill_store.store.attach_derived(etf_id, "fullView", payload)

    # ── Fetching ──────────────────────────────────────────────────────────────

    def _fetch(self, chunk: list[str], job: _Job) -> tuple[dict[str, TickerData], dict[str, str]]:
        """One batch: `({symbol: data}, {symbol: reason})`, keyed by the repo's
        symbol. A symbol is asked for in yfinance's spelling (BRK.B as BRK-B), and
        one that comes back empty under a spelling that differs is asked again as
        written, since a single-letter suffix can be an exchange (ABC.L)."""
        by_yahoo, collided = {}, {}
        for symbol in chunk:
            spelling = market_data.yahoo_symbol(symbol)
            if spelling in by_yahoo:
                # Two repo symbols with one yfinance spelling: only one can be
                # asked for, and the other must say so rather than vanish.
                collided[symbol] = (
                    f"it shares yfinance's spelling ({spelling}) with {by_yahoo[spelling]}, "
                    "which was fetched instead"
                )
            else:
                by_yahoo[spelling] = symbol
        got, failed = self._download(list(by_yahoo), job, transient_if_empty=True)
        fetched = {by_yahoo[y]: data for y, data in got.items()}
        failures = {by_yahoo[y]: reason for y, reason in failed.items()}

        respell = [s for s in failures if market_data.yahoo_symbol(s) != s]
        if respell:
            again, still = self._download(respell, job)
            fetched.update(again)
            for symbol in respell:
                failures.pop(symbol)
            failures.update(still)
        failures.update(collided)
        return fetched, failures

    def _download(self, symbols: list[str], job: _Job, transient_if_empty: bool = False):
        """Download `symbols` and split the answer per ticker, with the cooldown
        respected and a few attempts. Keyed by the symbol as passed in.

        `yf.download` does not raise for a ticker it could not fetch: it catches the
        error - a rate limit included - logs it and hands back an empty frame for
        that symbol. So a throttled batch arrives looking like fifty delisted
        symbols, and `_live` never sees the 429 that would start the cooldown. A
        batch of several tickers with *none* usable (`transient_if_empty`, for the
        first ask of a batch) is therefore treated as the upstream refusing, not as
        fifty bad tickers: waited out for the cooldown's length and asked again, and
        after `BATCH_ATTEMPTS` the job ends `failed` with what it has, to be resumed.
        A partly empty batch cannot be told from a few genuinely missing symbols, and
        names them as failures; asking again fetches whichever were only throttled.
        """
        attempts = 0
        while True:
            while market_data._rate_limit_cooldown.active():
                if _wait(job.cancel, market_data._rate_limit_cooldown.remaining()):
                    raise _Cancelled()
            try:
                frame = market_data._live("Deep-fill batch", _yf_download, symbols)
            except market_data.SymbolNotFound as exc:
                return {}, {s: str(exc) for s in symbols}
            except market_data.DataUnavailable as exc:
                attempts += 1
                if attempts >= BATCH_ATTEMPTS:
                    raise _GiveUp(f"yfinance could not be reached after {attempts} attempts: {exc}") from exc
                if _wait(job.cancel, exc.retry_after):
                    raise _Cancelled()
                continue

            fetched, failed = _split(frame, symbols)
            if fetched or not transient_if_empty or len(symbols) < 2:
                return fetched, failed
            attempts += 1
            if attempts >= BATCH_ATTEMPTS:
                raise _GiveUp(
                    f"yfinance returned nothing for a batch of {len(symbols)} tickers "
                    f"{attempts} times - most likely it is rate limiting this server"
                )
            if _wait(job.cancel, RATE_LIMIT_COOLDOWN_SECONDS):
                raise _Cancelled()


def _yf_download(symbols: list[str]) -> pd.DataFrame:
    return yf.download(
        symbols, period="1y", interval="1d", auto_adjust=True, actions=True,
        group_by="ticker", progress=False, threads=True,
    )


def _split(frame, symbols: list[str]):
    """Cut one download into per-ticker data. Returns `({asked: TickerData},
    {asked: reason})`, `asked` being the symbol as it was passed to yfinance."""
    fetched, failed = {}, {}
    none = (
        "yfinance returned no price history for it (it may be delisted, or not "
        "fetched under load - start again retries it)"
    )

    if frame is None or frame.empty:
        return {}, {s: none for s in symbols}

    if isinstance(frame.columns, pd.MultiIndex):
        if not any(s in frame.columns.get_level_values(0) for s in symbols):
            frame = frame.swaplevel(axis=1)
        parts = {s: frame[s] for s in symbols if s in frame.columns.get_level_values(0)}
    else:
        parts = {symbols[0]: frame} if len(symbols) == 1 else {}

    for symbol in symbols:
        part = parts.get(symbol)
        if part is None or "Close" not in part.columns:
            failed[symbol] = none
            continue
        part = part.dropna(subset=["Close"])
        if part.empty:
            failed[symbol] = none
            continue
        index = pd.to_datetime(part.index)
        if index.tz is not None:
            index = index.tz_localize(None)
        trimmed = part.reindex(columns=_FIELDS).copy()
        trimmed.index = index.normalize()
        dividends = []
        if "Dividends" in part.columns:
            paid = part["Dividends"].fillna(0)
            dividends = [
                (when.strftime("%Y-%m-%d"), float(amount))
                for when, amount in zip(trimmed.index, paid) if amount > 0
            ]
        fetched[symbol] = TickerData(frame=trimmed, dividends=dividends, fetched_at=deep_fill_store._now())
    return fetched, failed


# The one job manager. Tests replace this name with a fresh instance.
manager = DeepFill()


def start(etf_id: str) -> dict:
    return manager.start(etf_id)


def cancel(etf_id: str) -> dict:
    return manager.cancel(etf_id)


def status(etf_id: str) -> dict:
    return manager.status(etf_id)
