# backend — FastAPI service

Serves the dashboard, the measurement plugins and the portfolio simulator. Reads
from Supabase where it can and falls back to a live yfinance call where it
cannot; owns no user state of any kind.

Start it with `preview_start {name: "backend"}` (see `.claude/launch.json`), or:

```bash
python -m uvicorn main:app --port 8000 --reload
```

Or, without a local Python setup at all: `docker compose up` from the repo
root (see the README's "Running it with Docker") — same `--reload` behaviour,
`backend/` bind-mounted into the container.

Interactive API docs at `http://localhost:8000/docs`, liveness at `/health`.

## Layout

```
main.py                  app object, CORS, exception→status mapping, /health
config.py                TTLs, period→days table, sector-tag normalisation, doc-example defaults
api/routes.py            every /api endpoint except the measurement ones
services/                data access and arithmetic — see services/CLAUDE.md
measurements/            the column plugin system — see measurements/CLAUDE.md
scripts/                 the data pipeline — see scripts/CLAUDE.md
sql/                     migrations already applied, kept for review and history
tests/                   pytest suite for everything above
```

## The layering, and what may not cross it

```
routes.py ──> services/*        (never yfinance or supabase directly)
measurements/*/*.py ──> measurements/inputs/*   (never services/* directly)
services/* ──> yfinance, supabase
scripts/* ──> services.market_data's private _*_live helpers, supabase_client
```

Two of these are load-bearing:

- **Routes never call yfinance or Supabase.** They normalise input (uppercasing
  tickers), delegate to a service function, and translate exceptions into status
  codes. Caching and fallback live in the service.
- **Measurements never call `services.market_data` directly.** They go through
  `measurements/inputs/*`, which is what lets a measurement fetch everything it
  needs from an `etf_id` alone and lets its documentation page state the defaults
  those getters quietly apply.

The scripts deliberately reach *past* the caching layer into
`market_data`'s `_get_etf_info_live` / `_get_etf_holdings_live` /
`_get_stock_info_live`. That is correct: the scripts are what makes the DB fresh,
so a DB-first read there would write the same rows back in a circle, and they
want the real upstream exception rather than a re-wrapped one.

## Errors are the API

Three exceptions, three status codes, and the difference between them is the
whole reason the frontend recovers from a cold start instead of parking on an
error panel.

| Raised | Mapped in | Status | Meaning |
| --- | --- | --- | --- |
| `ValueError` | the route (`HTTPException(400, …)`) | 400 | the request cannot be answered as asked |
| `SymbolNotFound` | `main.py` handler | 404 | upstream answered, and the symbol does not exist |
| `DataUnavailable` | `main.py` handler | 503 + `Retry-After: exc.retry_after` | upstream could not be reached right now |

`useFetch` retries 5xx/429 and never retries a 4xx, on a backoff schedule
(`app/src/utils/retrySchedule.js`) rather than a flat interval — see issue
#92. So:

- Answering 503 for a typo means retrying it forever.
- Answering 404 for a Yahoo outage means the dashboard stays broken until
  someone reloads the page by hand.
- Answering 500 for either means both, plus a stack trace in the log that reads
  like a code bug.

`_live()` in `market_data.py` is the only place that converts a failed live call
into one of these, by reading the HTTP status off the exception chain
(`_upstream_status`). Do not add a blanket `except Exception` between a live call
and that helper — an early one is what let a cold-start blip be cached as "SPY
has no holdings".

`DataUnavailable.retry_after` defaults to 3, but it isn't always 3: an
upstream 429 (or a bare `YFRateLimitError`, which carries no status of its
own) starts a process-wide cooldown — `_RateLimitCooldown` in
`market_data.py` — that answers every request without even calling yfinance
until it expires, and reports the real time left as `retry_after`. This is
not a cache: a cache stores an answer per request and never one for a
failure; the cooldown stores no answer at all, only the one fact "yfinance is
rate-limiting us until T", checked by every live call regardless of what it
was asking for. Without it, every open tab's own retry became more of the
traffic that kept Yahoo's rate limit in place.

`measurements/registry.py` re-raises both exceptions untouched rather than
wrapping them in its generic 500, for the same reason.

Validation that both HTTP callers and internal callers need lives in the service
(`resolve_window` raises `ValueError` naming the offending parameter); the route
turns it into a 400. Do not duplicate it at the edge.

## Caching

`services/cache.py` is a process-local TTL dict, reset on restart. Three TTLs
from `config.py`:

- `CACHE_TTL_SECONDS` (900) — price series, correlation matrices.
- `CACHE_TTL_HOLDINGS` (3600) — ETF info/holdings, stock metadata, the tracked
  universe snapshot, resolved symbols.
- `CACHE_TTL_HOLDINGS_FALLBACK` (10) — used **only** when a read fell back to
  live because Supabase missed or errored. Ten seconds, so the next request
  retries the DB almost immediately rather than being pinned to a top-~10 live
  snapshot for a full hour.

Rules for adding a cached read:

- The cache key must contain everything that changes the answer. A price series
  key carries ticker, period, start, end and interval — two windows of the same
  ticker are different answers and must not serve each other's rows.
- **Never cache a failure.** An empty answer is a fact about the ticker and may
  be cached; an upstream failure is a fact about right now and must not be, or
  the next request inherits it.
- `cache.get()` distinguishes "not cached" (`None`) from a cached empty list, so
  do not skip a cache write just because the result is falsy.

This is single-process. A multi-worker deployment needs a shared cache, and
nothing here assumes otherwise beyond the comment saying so.

## Windows of history

Everything that reads a stretch of history takes either a `period` (a lookback
from today, in yfinance's vocabulary) **or** an explicit `start`/`end` — never
both. `market_data.resolve_window` is the one normaliser: it rejects the
combination, rejects a malformed date, an `end` in the future, and a `start` at
or after the `end`, each with a message naming the parameter.

`"max"` is the one period a caller cannot express as dates, because how far back
a basket reaches is a fact about its holdings. It travels to the backend as a
period and the response reports the window that actually got simulated.

Two subtleties that have bitten before:

- The DB filters `date <= end` (inclusive); yfinance's `end` is exclusive.
  `_exclusive_end` reconciles them so the same request cannot answer differently
  depending on which path served it.
- A window's bounds are compared against a row's `date`, which for a coarse row
  is the bucket **anchor**. A window opening mid-month therefore begins at the
  next anchor rather than reaching back into the bucket it landed in.

## Adding an endpoint

1. Put the logic in `services/`, with the validation, the caching and the
   DB-then-live fallback. Raise `ValueError` / `SymbolNotFound` /
   `DataUnavailable` as appropriate.
2. Add a thin route in `api/routes.py`, uppercase the ticker, translate
   `ValueError` to a 400, and write a docstring that says what the endpoint
   answers *and* what each failure mode means — the existing ones are the model.
3. Add the endpoint to the module docstring's endpoint list at the top of
   `routes.py`.
4. Add a client method in `app/src/utils/api.js`.
5. Cover it in `tests/`.

Route ordering matters: FastAPI matches in registration order, which is why
`/tickers/search` is declared before `/tickers/{symbol}`. Measurement doc routes
live under `/measurement-docs/...` rather than `/measurements/{id}/doc` for the
same reason — a plugin route `/measurements/correlation/{etf_id}` would happily
match `etf_id="doc"`.

## Tests

`backend/tests/`, run from the repo root with `pytest`. Each file opens with a
docstring saying what it pins down and why; keep that.

Conventions:

- Every test file does `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`
  so `backend/` is importable — there is no package install step and no
  `conftest.py` here.
- `TestClient(app, raise_server_exceptions=False)` is how the status-code
  contract is asserted end to end (`test_api_errors.py`, `test_symbol_not_found.py`,
  `test_transient_failures.py`).
- Simulations run against **synthetic** price frames so expected numbers are
  arithmetic a reader can check by hand, not whatever AAPL happened to do.
- Patch every reader a code path touches, not just the obvious one. The portfolio
  helpers patch `get_closes`, `get_dividends` **and** `tracked_tickers`; patching
  only prices left the tests reaching Supabase — eight seconds a run, and a
  different result depending on whether it answered.
- Supabase is faked with a write-hostile double where the point is that nothing
  is written.

## SQL

`sql/` holds migrations that were applied through Supabase's `apply_migration`
and are kept for review and history — they are **not** run by any script here,
and `003`'s file explicitly warns that text was added after the fact. Read them
for the reasoning (why `volume` stayed `bigint`, why `last_fetch` was reset), not
as a runnable state machine. A new migration should be added the same way: apply
it, then commit the file with the same kind of prose header.
