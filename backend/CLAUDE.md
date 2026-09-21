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
main.py                  app object, CORS, rate limiting, exception→status mapping, /health
config.py                TTLs, period→days table, sector-tag normalisation, doc-example defaults
rate_limit.py            per-client request limiting on /api/* — see "Errors are the API"
api/routes.py            every /api endpoint except the measurement/portfolio-metric ones
services/                data access and arithmetic — see services/CLAUDE.md
measurements/            the column plugin system — see measurements/CLAUDE.md
portfolio_metrics/       the portfolio summary tile registry (issue #104), mirroring measurements/ — also holds the fund-level metrics card's registry entries (issue #105)
scripts/                 the data pipeline — see scripts/CLAUDE.md
sql/                     migrations already applied, kept for review and history
tests/                   pytest suite for everything above
```

## The layering, and what may not cross it

```
routes.py ──> services/*        (never yfinance or supabase directly)
measurements/*/*.py ──> measurements/inputs/*, services/stats.py   (never services.market_data directly)
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
  those getters quietly apply. `services/stats.py` is the one deliberate
  exception (its own module docstring says so, issue #98): pure arithmetic, no
  I/O, so a measurement (issue #107's risk_contribution/fund_relation/
  tail_correlation/capture_ratio) may call it directly rather than through an
  `inputs/*` wrapper that would add nothing.

The scripts deliberately reach *past* the caching layer into
`market_data`'s `_get_etf_info_live` / `_get_etf_holdings_live` /
`_get_stock_info_live`. That is correct: the scripts are what makes the DB fresh,
so a DB-first read there would write the same rows back in a circle, and they
want the real upstream exception rather than a re-wrapped one.

## Errors are the API

Three exceptions map onto three of these status codes, and the difference
between them is the whole reason the frontend recovers from a cold start
instead of parking on an error panel. The fourth, 429, isn't an exception at
all — `RateLimitMiddleware` (`rate_limit.py`) decides it before a route ever
runs, the same way `CORSMiddleware` can answer a preflight without one.

| Raised | Mapped in | Status | Meaning |
| --- | --- | --- | --- |
| `ValueError` | the route (`HTTPException(400, …)`) | 400 | the request cannot be answered as asked |
| `SymbolNotFound` | `main.py` handler | 404 | upstream answered, and the symbol does not exist |
| *(none — `RateLimitMiddleware`)* | `rate_limit.py`, before the route | 429 + `Retry-After` | this client exceeded its own request budget (issue #93) |
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

## Bounding one anonymous client (issue #93)

The API has no accounts (see "Where portfolios live, and why there is no
account" in the README), so every request is anonymous. Three independent
limits, none of them new status codes beyond the 429 above:

- **`rate_limit.py`'s two `FixedWindowLimiter`s** — a general one on every
  `/api/*` request and a tighter one just for `POST /api/portfolio/simulate`,
  both per client (`X-Forwarded-For`, Render's convention for the real
  address — never the socket peer, which on Render is always the proxy).
  In-process and per-instance by design, like `_rate_limit_cooldown` above;
  a multi-instance deployment would need a shared store instead. `/health` is
  never limited, or Render's own health check could take the service down.
- **`market_data._throttled_force_refresh`** — `GET /api/etf/{id}?refresh=true`
  reaches upstream at most once per `FORCE_REFRESH_THROTTLE_SECONDS` (5 min)
  for that ETF. Per-ETF, not per-client: the cost it guards is an upstream
  call for that fund, whoever asks. A refresh inside another one's window is
  served like a normal cached request, not refused.
- **`services/portfolio.py`'s `MAX_HOLDINGS`** (50) bounds one simulation's
  basket size. Measured against a real 512MB-capped container rather than
  guessed: a 100-holding, 32-year run peaked at 174MB, so this was never
  actually close to a memory ceiling — the real thing it bounds is latency
  and CPU for a request from a caller who has proven nothing about who they
  are.

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

## The risk-free rate (issue #103)

Sharpe and Sortino (filed separately, issue #112) are the first metrics
needing data this app does not otherwise have. Invariant 4 forbids a
hardcoded ticker list, and a single fixed rate would be meaningfully wrong
besides — the windows this app can already simulate span years over which
short rates moved several points — so the rate is tracked like everything
else the pipeline tracks: its own table (`risk_free_rate`,
`sql/004_track_risk_free_rate.sql`), refreshed daily by
`scripts/fetch_daily.py`'s `sync_risk_free_rate` alongside prices,
dividends and splits, read back by `services.market_data.get_risk_free_rate`.

Four things distinguish it from a price series:

- **Not even the upstream symbol is hardcoded.** Invariant 4 applies to
  this series exactly the same way it applies to the tracked ETF/stock
  universe: which yfinance symbol backs the rate lives in
  `risk_free_rate_source` (one row, seeded once by the migration itself,
  changeable as a database edit rather than a deploy), not a Python
  constant. `scripts.fetch_daily._risk_free_rate_symbol` reads it; an
  empty table (the seed row deliberately removed) skips the sync rather
  than falling back to a guess.
- **It is a yield, not a price.** Stored exactly as read — a percentage
  per annum — so none of the adjusted-close rules in "How prices are
  stored" apply to it, and there is nothing to bucket by age: one flat,
  densely-populated table, not three tiers.
- **No live fallback**, the same reasoning `get_dividends` already gives:
  a number that sometimes comes from a record and sometimes from a
  network call is a number nobody can reconcile. `get_risk_free_rate`
  returns `None`, not an empty list, when Supabase is unreachable or
  nothing has been synced for the window asked — a caller scoring a run
  against it must show a null with a reason, never an assumed zero.
- **Overridable, not just readable.** `PortfolioIn.rate` (percent per
  annum) lets a caller — the frontend's `?rf=`, via `useRiskFreeRate.js`
  — replace the tracked series for one run, read by `simulate_portfolio`
  for Sharpe and Sortino (issue #112). `POST /api/portfolio/risk` (issue
  #113) accepts the same `PortfolioIn` body for shape parity — a caller
  can send it the exact request it built for `simulate` — but does not
  read `rate` at all: what it answers (correlation, effective bet count,
  per-holding risk share) is a property of the basket's price history,
  not of anything scored against a risk-free rate.

## Freshness (issue #154)

The header says whether the data being read comes from a recent run of the daily
fetch job or an old one. The reasoning is `docs/adr/0003-the-daily-job-records-its-own-runs.md`;
the code is `services/freshness.py` and `GET /api/freshness`; the rest is where
the rules touch the ones above.

- **The job records itself, and the record is read, not inferred.** One
  `fetch_run` row per run (`sql/005_record_daily_job_runs.sql`), written by
  `scripts/fetch_daily.py` before compaction. `ticker.last_fetch` is not used:
  it is a date on the runner's clock and GitHub starts the cron up to hours late.
- **The backend names the deadline, the browser compares.** `dueBy` is the first
  scheduled slot strictly after the run *finished*, plus a 12-hour grace, so the
  answer can be cached for `CACHE_TTL_SECONDS` and still turn behind on time,
  with no calendar logic in the client. `config.py`'s `FETCH_SCHEDULE_*` is a
  second copy of the cron line in `.github/workflows/fetch-daily.yml`;
  `tests/test_freshness.py` parses that file and fails if they differ. **Change
  the cron and `config.py` together.**
- **The status codes follow "Errors are the API" above.** Nothing to report — no
  Supabase configured, no run yet, or the table not created yet (the migration is
  applied by hand, so the backend can be deployed first) — is a `200` of nulls,
  because a 503 would have the frontend retry, on a backoff, something that never
  changes on its own. Supabase configured but unreachable or unreadable is
  `DataUnavailable` → `503`, retried, never a `500` — including credentials set
  but no client buildable, which is a cold start (`get_client_optional` returns
  `None` for that exactly as for a missing config; only the environment says
  which). Only a found run is cached; an absent answer and a failure are not.
- **A figure the run cannot support is `null`, never `0`** (invariant 7):
  `failed: 0` means a run finished and refreshed everything, and `null` means
  there is no run to describe.
- **It is not the `stale` flag.** `stale` on `GET /api/etf/{id}` means the
  holdings came from the live top-~10 fallback, a completeness fact; a fund in
  that state is as current as it gets. Do not reuse the word for age.

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
- **Every `TestClient` reports the same address** (`("testclient", 50000)`), so
  every `/api/*` call made anywhere in this suite shares one bucket on the real
  `rate_limit.general_limiter`/`simulate_limiter` (issue #93) — there is real,
  if generous, headroom (33 such calls across the whole suite today against a
  120/min default), but a test that needs to actually trip a limit patches in
  a fresh `FixedWindowLimiter` (`test_rate_limit.py`) rather than looping real
  requests against the shared singleton, the same way a 429 test patches a
  fresh `_RateLimitCooldown` instead of touching the real one (issue #92).

## SQL

`sql/` holds migrations that were applied through Supabase's `apply_migration`
and are kept for review and history — they are **not** run by any script here,
and `003`'s file explicitly warns that text was added after the fact. Read them
for the reasoning (why `volume` stayed `bigint`, why `last_fetch` was reset), not
as a runnable state machine. A new migration should be added the same way: apply
it, then commit the file with the same kind of prose header.
