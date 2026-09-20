# Market Analyser — repository guide

ETF correlation dashboard and portfolio simulator. React/Vite frontend, FastAPI
backend, Supabase (Postgres) as the store of record, yfinance as the upstream
market-data source, and a set of Playwright scrapers that pull full ETF holdings
from provider websites.

`README.md` is the product-level reference and is unusually complete — the data
pipeline, the price-storage rules, the measurement plugin format, and the entire
portfolio-simulation model are documented there. **Read the relevant README
section before changing behaviour it describes, and update it in the same change
if the behaviour moves.** The README is treated as part of the contract, not as
a courtesy.

## Repository map

| Path | What lives there |
| --- | --- |
| `backend/` | FastAPI service, Supabase access, portfolio arithmetic, measurement plugins, data-pipeline scripts, SQL migration history |
| `fetcher/` | One Playwright scraper per ETF provider (VanEck, SPDR, ARK, iShares, Vanguard, Invesco), writing a shared holdings-JSON schema |
| `app/` | React 19 + Vite 8 + Tailwind 4 frontend |
| `tests/` | Tests for `fetcher/` only (fixture-driven, no network) |
| `backend/tests/` | Tests for `backend/` (service + scripts + measurements) |
| `.github/workflows/` | Daily price refresh (cron), manual holdings fetch + DB completion, pytest and the frontend's Vitest on push/PR, Docker image build check |
| `.claude/launch.json` | Dev-server definitions for the Browser pane (`backend` on :8000, `app` on :5173) |
| `docker-compose.yml` | Alternative way to run the stack — see "Running it with Docker" in the README. Not what `preview_start` drives. |
| `render.yaml` | Render Blueprint that deploys `backend/Dockerfile`'s `prod` target and `app/`'s static build — see "Deploying on Render" in the README. |

Each of `backend/`, `backend/services/`, `backend/measurements/`,
`backend/scripts/`, `fetcher/`, `app/`, `app/src/components/portfolio/` and
`tests/` has its own `CLAUDE.md` with the conventions specific to it.

## Running it

Backend (from `backend/`):

```bash
python -m uvicorn main:app --port 8000 --reload
```

Frontend (from `app/`):

```bash
npm install && npm run dev
```

Both are also defined in `.claude/launch.json`, so `preview_start` with
`{name: "backend"}` or `{name: "app"}` starts them — **always prefer that over
running a dev server through Bash.** The frontend talks to
`http://localhost:8000/api` unless `VITE_API_BASE` says otherwise; the backend
accepts cross-origin requests from `localhost:5173` and `localhost:3456` unless
`CORS_ORIGINS` says otherwise.

The backend boots and serves with **no** Supabase configuration at all — every
read falls back to a live yfinance call. That is a deliberate degraded mode, not
an accident: `get_client_optional()` never raises. A local run without
`backend/.env` therefore works, but returns yfinance's top-~10 ETF holdings
instead of the full constituent lists and reports `stale: true`.

`docker compose up` runs the same two dev servers in containers instead — see
"Running it with Docker" in the README for what that gets you and the couple
of things (the frontend's API base, `node_modules`) that need to work
differently in a container than natively. It's an alternative, not the
default: `preview_start` still drives the native processes above, not the
containers.

The only deployed copy runs on Render, from `render.yaml` — see "Deploying on
Render" in the README. It builds the same `prod` Docker targets `docker-build.yml`
already checks on every PR, not the `dev` targets compose runs; the data
pipeline (this section, and #91's context) stays on GitHub Actions regardless
of where the API and frontend are hosted.

## Tests

```bash
pip install -r backend/requirements.txt -r fetcher/requirements.txt -r requirements-dev.txt
pytest
```

`pytest.ini` sets `testpaths` to both trees. Backend tests are unittest-style
classes, fetcher tests are plain assert functions, and both run under pytest. The
only `conftest.py` is `tests/conftest.py`, which does nothing but put `fetcher/`
on `sys.path` the way running a fetcher as a script would; backend tests each
insert `backend/` themselves.

**No test may touch the network or Supabase.** Backend tests patch the seam they
need (`services.portfolio.get_closes`, `services.market_data.get_client_optional`,
`yfinance.Ticker`, …) and fetcher tests parse checked-in fixtures under
`tests/fixtures/`. A test that got slower or flakier because it reached a real
service is a bug in the test.

The frontend has two automated checks: `npm run lint` (ESLint with react-hooks
and react-refresh rules) and `npm test` (Vitest, run from `app/`). The suite is
deliberately small — plain functions over pure logic, no DOM environment, no
component tests — and today covers only pure modules: the `store/` ones that
decide what a portfolio may be and how it travels (`portfolioBackup.js`, issue
#148; `portfolioLink.js` and `portfolioStorage.js`, issue #150), the one that holds
the candle switch (`candlePreference.js`, issue #152), and the `utils/` ones that
decide which candles a price chart draws and what hovering one says
(`candles.js`, `chartTooltip.js`). Logic that is worth
testing goes in a pure module and is tested through its public function, the
way `planImport` is; components, hooks and dialogs are checked by using the
running app.

`docker compose run --rm tests` (with pytest args passed through, or
`docker compose run --rm tests lint` for the ESLint check, `... tests frontend`
for Vitest) runs the same checks in a container built from the repo root — see
`Dockerfile.tests`. It exists for parity with CI, not to replace running pytest
directly.

## Environment and secrets

`backend/.env` and `app/.env` are gitignored; the `.env.example` beside each one
is the documented shape. The only backend credential is `SUPABASE_SERVICE_KEY` —
the **service role** key, which bypasses row-level security. RLS is enabled on
`ticker`/`prices` with no public policies, so nothing else can read them. Never
expose that key to the frontend, never add a frontend-reachable path that lets a
request choose what it reads, and never commit it. In `docker-compose.yml`,
`backend/.env` is loaded only into the `backend` service for the same reason —
it must never become a shared `env_file` the `app` service also reads. On
Render, the same rule means `SUPABASE_SERVICE_KEY` is set on the API service
only, and never in an environment group also linked to the static site.

That single credential is also why there are no user accounts — see "Portfolios
live in the browser" below.

## Workflow conventions

Work is tracked as GitHub issues and lands through PRs:

- Branch name: `<issue-number>-<kebab-case-issue-title>`, e.g.
  `86-price-the-whole-basket-when-supabase-holds-only-part-of-it`.
- Commit subject: imperative, sentence case, naming the issue —
  `Price the whole basket when Supabase holds only part of it (closes #86)`.
  The trailing `(#88)` is appended by the squash merge; do not write it yourself.
- Commit body: prose, usually several paragraphs, explaining **why** and what was
  verified. Read `git log` for the register — these bodies are the project's
  design record and are worth matching.
- **No attribution trailers.** No `Co-Authored-By`, no "Generated with" footers,
  in commits, PR bodies or issues. The repository has one author, and the history
  contains zero such trailers.

Commit or push only when asked, and never directly to `main`.

## House style

The comment culture here is unusual, and preserving it matters more than any
individual convention below.

- **Module docstrings carry the model, not a summary.** `services/portfolio.py`
  opens with the entire simulation model; `market_data.py` opens with the
  read/fallback/cache pattern every function in it follows. When you change
  behaviour, change the docstring that states it — a stale docstring here is
  worse than none, because the rest of the codebase is written trusting it.
- **Comments explain the decision and the failure it prevents**, often with an
  issue number (`issue #13`, `#86`). Keep that habit: a comment restating what
  the code does is noise; one saying why the obvious alternative was wrong is the
  reason the file reads the way it does.
- **Prefer the plain word to the jargon** in user-facing copy, and say what a
  number does *not* mean as readily as what it does.
- Backend: 4-space indent, `from x import y`, type hints on public functions,
  `snake_case`, section banners (`# ── Name ───`). Frontend: 2-space indent,
  named exports, function components, Tailwind utilities over CSS variables.

## Cross-cutting invariants

These hold across the whole repo. Breaking one is a bug even where it looks
locally reasonable.

**1. The HTTP status code is a contract with the frontend's retry logic.**

| Status | Meaning | Frontend behaviour |
| --- | --- | --- |
| 400 | The request cannot be answered as asked | never retried |
| 404 | The thing asked for does not exist | never retried |
| 429 | This client is asking faster than its own limit allows | retried on a backoff schedule |
| 503 | The upstream could not be reached *right now* | retried on a backoff schedule |

`DataUnavailable` → 503 and `SymbolNotFound` → 404 are mapped in
`backend/main.py`; `app/src/utils/api.js`'s `isTransientError` and
`hooks/useFetch.js` are the other half. Collapsing the two exceptions is how a
typo'd ticker got re-requested forever, and how one cold-start blip wedged the
dashboard permanently. Do not catch either broadly, and do not answer 500 for
"the data source is down".

The 503's `Retry-After` is not always the same number (issue #92). A cold
start or a generic outage sends 3, the frontend's usual starting point; Yahoo
rate-limiting the backend's own outbound calls sends however many seconds are
left on the cooldown `services/market_data.py` enters until it's willing to
call yfinance again — up to 60. `app/src/utils/retrySchedule.js`'s auto-retry
schedule (3s doubling to a 60s cap, giving up after 8 attempts) never waits
less than that header says, on either side: retrying a rate limit every 3s is
exactly the traffic that keeps it in place, and giving up forever would make
a slow-but-recoverable failure look permanent.

429 is a different upstream from 503, but the same contract: `backend/rate_limit.py`
answers it, with its own `Retry-After`, when one client (identified by the
`X-Forwarded-For` Render forwards, not the socket peer) exceeds its own
per-minute budget on `/api/*` — a general one, and a tighter one just for
`POST /api/portfolio/simulate` (issue #93). The frontend needs no changes for
this: `isTransientError` already treats 429 the same as a 5xx.

**2. Prices are adjusted, always, and history is tiered by age.** `prices` holds
split- and dividend-adjusted OHLC (`auto_adjust=True` is passed explicitly on
*every* path so the DB and the live fallback cannot drift — issue #13). Rows
under a year old are daily `D`; one to five years, weekly `W`; older, monthly
`M`. A coarse row's `date` is its **bucket anchor** (Monday of the ISO week, 1st
of the month) while its `close` is the bucket's **last** close — different days,
which anything aligning another series onto this calendar must respect (see
`_onto_calendar` in `market_data.py`). Never assume one row is one trading day.

**3. Every Supabase read whose row count can grow must paginate.** PostgREST
silently truncates at 1000 rows with no error. Use
`services.supabase_client.paginated_select(lambda: …)` — a **fresh** builder per
page, always with a deterministic `ORDER BY`. For a read you are certain stays
tiny, `assert_not_truncated` makes a future truncation loud instead of silent. A
bare `.select().execute()` on a growable table is a defect (issue #14).

**4. The tracked universe is database-driven.** There is no hardcoded ETF or
ticker list anywhere. The `etfs` table decides which funds are tracked and the
scripts fill in the rest. Do not introduce a constant list of symbols.

**5. Portfolios live in the browser.** `localStorage`, key
`market-analyser.portfolios`. There is no `portfolios` table and there must not
be one: with only a service key and no sign-in, a server-side table would be one
shared, world-editable list. `POST /api/portfolio/simulate` reads nothing and
stores nothing — the portfolio arrives in the request and leaves in the response.
The one way out of the browser is a file the *owner* holds: a Backup (export/import,
issue #148) or a Share Link. Neither is a server-side store, and importing one only
ever adds — it never replaces or deletes a saved portfolio (`docs/adr/0001-*`).

**6. Backend-authored MDX executes as real JSX in the browser.** Measurement
cells (`render_cell`) and measurement docs (`.mdx`) are compiled and run by
`MdxCell.jsx` / `DocMdx.jsx`. That is safe *only* because both are first-party
files reviewed like code. Never interpolate fetched or user-supplied text into
either.

**7. Absence has to be interpreted, never defaulted.** A figure a run cannot
support is `null`, not `0`; a holding the `dividends` table has no record of
reports `null` and is named in `incomeUnknownFor`, because answering it with `0`
would state that SPY pays no dividend. This pattern recurs throughout — resist
the tidier-looking zero.

## Platform notes

Windows 11, PowerShell primary with Git Bash available. A local `.venv/` sits at
the repo root and is gitignored; `app/dist/` is build output and is not tracked.
`.claude/` is gitignored, so `settings.local.json` and `launch.json` are
local-only — the `CLAUDE.md` files themselves are tracked and are meant to be.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for MCR-Project/Market-Analyser; the `gh` CLI handles all operations. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context layout: `CONTEXT.md` + `docs/adr/` at the repo root, created lazily. See `docs/agents/domain.md`.
