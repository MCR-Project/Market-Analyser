# backend/scripts — the data pipeline

Four scripts maintain the tracked universe in Supabase. All are run from
`backend/` and need `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in `.env`. None of
them is imported by the running service; they reach past `market_data`'s caching
layer into its private `_*_live` helpers on purpose, because they are what makes
the DB fresh — a DB-first read here would write the same rows back in a circle.

| Script | Job | Trigger |
| --- | --- | --- |
| `add_ticker.py` | Add or update tickers by hand | manual |
| `complete_database.py` | Complete tracked ETFs from provider holdings JSON | `fetch-holdings.yml` (cron, 06:00 UTC Sundays, or manual dispatch) |
| `sync_untracked_metadata.py` | Keep descriptive data for every Untracked holding | `fetch-holdings.yml`, after the completion (same Sunday cron, or manual dispatch) |
| `fetch_daily.py` | Refresh prices, metadata and ETF holdings for everything tracked | `fetch-daily.yml` (cron, 22:30 UTC Mon–Fri) |

## How something enters the universe

An ETF is tracked by having a row in `etfs` — inserted by hand through the
Supabase dashboard or SQL. Nothing in this repo adds one. `complete_database.py`
then fills in its metadata, its constituent tickers and their price history from
a holdings JSON produced by a `fetcher/` scraper; `fetch_daily.py` keeps
everything fresh from then on.

**The daily job never scrapes.** It only refreshes each fund's top ~10 weights
from yfinance, so a fund's full constituent list and its tracked/untracked split
move only when `fetch-holdings.yml` runs — weekly, Sundays, so it never overlaps
the Monday–Friday daily job (issue #169). That workflow is the only thing that
runs `complete_database.py` in CI, and it runs it **once**: the six provider
scrapes run in parallel (`fail-fast: false`, each uploading its JSON as an
artifact), then a single `complete` job `needs` all of them, runs even if some
failed, and passes every artifact that exists in one `--holdings-json` list. Two
completions at once would race on the DB-wide split, which is also why the
workflow has a `concurrency` group — a scheduled run and a manual dispatch queue
rather than overlap.

A provider whose scrape failed uploads nothing, so its funds are reported as
"not covered" and their rows are untouched; the run is red because that scrape
job was, while the other providers still complete. A fund-level `error` inside an
otherwise successful scrape does **not** fail the scrape — `complete_database.py`
skips it, as before — but a scrape where *every* fund errored does
(`run_fetcher` exits 1 after writing the file), since that is a provider that is
down, not a bad fund. `tests/test_fetch_holdings_workflow.py` pins this shape.

A stock enters either as a constituent weighing at least **1%** of a covered ETF
(`MIN_HOLDING_WEIGHT_PCT`), or by hand via `add_ticker.py`. Below the threshold it
is **Untracked** (issue #168, ADR 0005, `CONTEXT.md`): listed in `etf_holdings`
with its weight and `tracked = false`, with no `ticker`, `prices`, `dividends` or
`splits` row and no daily fetch. An existing stock is **demoted** — those rows
deleted, its holding rows kept — when it is below the threshold in *every* ETF that
holds it. Stocks held by no ETF at all (hand-added watchlist entries) have no
holding row to be judged by and are never demoted.

`etf_holdings.tracked` is a fact about the **stock**, denormalised onto every one of
its rows: true when its highest weight across every fund holding it clears the
threshold *and* it has a `ticker` row. Only `complete_database.py` writes it, and
always onto all of a stock's rows at once (`retag_stocks` updates by `ticker`,
never by row) — a stock at 0.4% in one fund and 2% in another is tracked in both.
`etf_holdings.ticker` has **no foreign key** any more (`sql/006`), so the promise
"tracked implies a `ticker` row" is kept by code, not by the database: anything
that upserts holdings for a ticker it has no row for would take the column default
`true` and list a holding nothing can price. `sync_etfs`'s `known_tickers` filter
is what stops the daily job doing exactly that, and the rows it does write carry
an explicit `tracked` copied from the stock's other rows (`_tracked_by_stock`), so
a stock still awaiting its backfill does not get a `true` row among `false` ones.
Only `complete_database.py` ever *changes* a stock's flag.

An Untracked stock's description lives in `untracked_metadata` (issue #170,
`sql/007`): the same descriptive columns as `ticker`, keyed by symbol, plus
`checked_at` and a `failure` reason, and **no prices of any kind** — a Deep-fill
fetches those live and writes nothing (ADR 0006). Three things write it, and
nothing else may:

- `complete_database.py`'s `demote_stocks` **copies** the stock's `ticker` row
  across (`copy_ticker_metadata`) before deleting that row, so a demoted stock
  keeps its metadata with no `.info` call. The copy never blocks the demotion — a
  failure prints a warning and the weekly lookup fetches the stock instead — and a
  `ticker` row with a null sector (the never-synced sentinel) is not copied as if
  it were an answer.
- `complete_holdings` deletes the row of every stock it flags Tracked
  (`drop_metadata`): a promoted stock's metadata is `ticker`'s now.
- `sync_untracked_metadata.py` (below) looks up the rest and sweeps the orphans.

The table has no foreign key, for the reason `etf_holdings.ticker` has none: its
symbol has no row to reference. Those three writers keep it honest, so a new one
has to keep the same rule — one row per symbol that is Untracked, none for one
that is not.

The risk-free rate's upstream symbol (issue #103) enters the same way an ETF
does: a row in `risk_free_rate_source`, seeded once by
`sql/004_track_risk_free_rate.sql` rather than by any script — invariant 4
("no hardcoded ticker list anywhere") applies to it too, so it is a database
fact `fetch_daily.py` reads, never a Python constant. Changing which symbol
is tracked is a database edit; removing the row entirely stops the sync
rather than falling back to a guess.

## `fetch_daily.py`

Seven phases, in order:

0. **`sync_risk_free_rate`** (issue #103) — refresh the tracked risk-free rate
   series (`risk_free_rate`), for whichever symbol `risk_free_rate_source`
   names (see "How something enters the universe" above): a full backfill
   the first time the table is empty, a small top-up otherwise. One flat
   series, not per-ticker, so "does the table have any rows yet" stands in
   for the per-ticker `last_fetch` column this table has no need of, and
   it runs even on a day nothing else needs syncing.
1. **`sync_etfs`** — refresh `etfs` metadata and `etf_holdings` weights for every
   ETF in the DB. The DB rows are the full constituent list (tracked and
   untracked) and the source of truth; yfinance only exposes the top ~10, so the live call refreshes the
   weights it knows about and **never shrinks** the DB set. Empty fields from
   yfinance are left out of the upsert so a flaky response cannot blank values
   the completion script already filled. Only **tracked** holding rows are read
   back (issue #168), and live holdings for a ticker with no `ticker` row are
   skipped, not failed — and must stay skipped, see "How something enters the
   universe".
2. **Price sync** — a full `max` backfill when `last_fetch` is null, otherwise a
   5-day top-up covering weekends, holidays and a missed run.
3. **Split/dividend escalation** — if a top-up turns up a corporate action that
   is not already recorded, the ticker is escalated to a full re-backfill on the
   spot. Both kinds force it: `prices` stores adjusted OHLC and yfinance's
   adjustment factor incorporates dividends as well as splits, so either one
   retroactively rescales the ticker's entire history. `_has_new_events` checks
   against `splits`/`dividends` first, so a date merely still inside the rolling
   5-day window is not re-escalated every run forever.
4. **Metadata refresh** — sector, market cap, currency, exchange, logo, website,
   for active tickers only.
5. **`record_run`** (issue #154, ADR 0003) — write one `fetch_run` row: `failed`,
   the number of distinct ids the run could not refresh (ETF sync, the
   risk-free rate, prices, metadata), with `finished_at` stamped by the database.
   This is what the header's Freshness reads. It sits **before** compaction on
   purpose: compaction only tidies storage, so its failures are not counted as
   data that is old, and a compaction crash cannot hide a fetch that had already
   finished. The "no tickers to sync" exit writes one too, since that run
   finished. A run that crashes before this point leaves **no** row, and so does
   one whose own write fails (the job then carries on, finishes compaction and
   exits 1) — a row would claim a finish for a run that did not finish, which is
   the one thing the record must never say. The row is new schema:
   `sql/005_record_daily_job_runs.sql` has to be applied before the first run
   that writes to it.
6. **`compact_ticker`** — sweep every known ticker (active or not) and promote
   aged buckets to a coarser tier.

### Tiering and compaction

`WEEKLY_TIER_START_DAYS = 365`, `MONTHLY_TIER_START_DAYS = 5 × 365`. A backfill is
tiered by `bucket_by_age` *before* it is written, so a long-lived ticker never
even transiently stores years of raw daily rows.

A bucket is only ever compacted once it has **fully elapsed** past its cutoff —
every one of its days is already older. That is what makes each bucket aggregate
exactly once, from complete data, whether it happens on a fresh backfill or later
in a compaction sweep.

`compact_ticker` is **crash-safe by design** (issue #16). A prior run can have
upserted the coarse row and died before deleting the daily sources it was built
from; re-aggregating those leftovers would silently overwrite a correct candle
with one built from a fraction of the period. So each pass first reads which
coarse rows already exist for the candidate anchors and, for a bucket that has
one, only deletes the leftover sources. A persistently nonzero
"already compacted, sources cleaned up" count across runs means the job keeps
dying mid-compaction, not one-off leftovers.

`_resample` collapses a bucket: first open, max high, min low, **last** close,
summed volume, dated at the bucket **anchor**. `volume` must stay `bigint` — a
monthly bucket sums ~21 days and overflows int4 for any high-volume ticker.

### Which tickers a run touches

`_select_tickers_needing_sync` reads `ticker` rows only, so an Untracked stock —
which has none — can never match it. It returns every active ticker **plus** any
inactive one whose `last_fetch` is null. That second half exists so a prices-convention
migration (like `sql/003`, which resets `last_fetch` for every row) reaches
inactive tickers too — otherwise `active=False` would strand them on the old
convention forever. Metadata refresh stays active-only regardless, and once
`last_fetch` is set an inactive ticker goes back to being skipped.

Idempotency: `(ticker, date, granularity)` is the primary key on `prices`, so
re-upserting a day overwrites the same row. The script exits 1 if anything
failed, listing what.

## `complete_database.py`

```bash
python scripts/complete_database.py --holdings-json ../vaneck_holdings.json [--dry-run] [--etfs SMH] [--min-weight 1.0]
```

Seven stages: load and merge the JSON files (skipping entries the fetcher flagged
with an error or that carry no holdings), intersect with the ETFs actually
tracked in `etfs`, complete ETF metadata, normalise holdings tickers, insert and
backfill new tickers above the weight threshold, upsert **every** constituent
into `etf_holdings` with its `tracked` flag, then demote everything DB-wide that
fell below the threshold.

- **The DB stays the source of truth for *which* ETFs are tracked.** The JSON
  only completes them; uncovered DB ETFs are reported and left to the daily job.
- `normalize_symbol` skips Bloomberg-style non-US ids (anything containing a
  space, e.g. `NPN SJ`) without burning a yfinance call, dots slash share classes
  (`BRK/B` → `BRK.B`), then merges known aliases through
  `market_data.DUPLICATE_TICKERS`.
- `validate_and_build_ticker`'s single `fetch_ticker_rows` call doubles as the
  "yfinance actually has data" validation and the backfill payload. No price
  history means the symbol is rejected, not inserted.
- If the live metadata lookup fails, the ticker is still inserted with the
  holdings file's name and a **null sector** — the sentinel that makes the next
  `fetch_daily` run repair it.
- `last_fetch` is stamped only **after** a full successful backfill, so a partial
  write self-heals: the next daily run re-backfills that ticker automatically.
- `plan_tracking` (pure) decides every stock's flag from the stored rows read once
  before any write (paginated, deterministic order — invariant 3, and the reason a
  stock is not demoted on a truncated read), with this run's weights replacing the
  stored ones for the same fund/stock pair. `retag` is the stocks whose rows in
  funds *outside* this run's files need the new flag; `demote` is decided by
  weight alone, so a stock flagged untracked only because its backfill failed
  keeps its half-written `ticker` row for the next daily run to finish.
- Demotion flags first, then deletes `dividends`, `splits`, `prices` and finally
  the `ticker` row (FK order — `etf_holdings` is no longer one of them). A run
  that dies in between leaves an untracked holding with a stale `ticker` row,
  which the next run demotes again; the reverse order would leave a tracked
  holding with nothing behind it.
- `PRICE_UPSERT_CHUNK = 5000`, because a `max` backfill can exceed 10k rows;
  `HOLDING_UPSERT_CHUNK = 1000`, because a total-market fund lists thousands of
  constituents now that the light ones are written too.

Every write is an upsert keyed on the primary key, so a second run finds 0 new
tickers, demotes nothing and changes nothing. Use `--dry-run` first when in doubt.

## `sync_untracked_metadata.py`

```bash
python scripts/sync_untracked_metadata.py [--dry-run]
```

The last job of `fetch-holdings.yml` (`untracked-metadata`, `needs: complete`,
`if: ${{ !cancelled() }}` — it runs when a scrape or the completion went red, since
it reads the `tracked = false` flags as they stand). One pass:

- **What is looked up** (`plan_lookups`, pure): every distinct symbol with a
  `tracked = false` holding row, read paginated; symbols with no row **first**, so
  a run cut short spends its calls on what a Deep-fill cannot describe at all, then
  rows checked 7 or more calendar days ago, oldest first. The age is in **calendar
  days, not hours**: GitHub starts the cron hours late by a different amount each
  week (ADR 0003), and 7 × 24 hours would skip a row last checked at 07:40 on a run
  starting at 06:30, doubling its wait. A **failed** row is the exception: it is
  always due, on every run, however recently it failed (order: new symbols, then
  failed ones, then stale ones). `get_untracked_info` refuses a row carrying a
  failure, so until it succeeds a Deep-fill cannot describe the symbol, and waiting
  a week after a transient outage would leave it that way; a manual re-run is how
  that gets fixed. The cost is bounded to the few symbols that raised — a symbol
  yfinance merely has nothing on is stored as "nothing there", not as a failure, so
  it is not retried every run.
- **How** — through `_get_stock_info_live`, one symbol and one upsert at a time
  (a failed row carries fewer columns than a good one and PostgREST rejects a bulk
  payload with mixed keys; it also means a run that dies keeps what it finished). A
  lookup that raises writes `checked_at` and `failure` **only**, so a stock that once
  had data does not lose it to one bad week, and `get_untracked_info` still declines
  to use the row. A write that fails is counted as a failure too, not as a lookup.
  **`_get_stock_info_live` does not raise for a symbol yfinance has nothing on** — it
  answers an empty shell (name = the symbol, sector "Unknown", no market cap, an
  assumed "USD"), which is what the Stock page shows. Stored as given, that is an
  "Unknown" sector and a currency nobody looked up, served as fact. So a shell is
  stored as **looked up, nothing there**: every descriptive column null, no failure
  (cash lines, futures and delisted names would otherwise keep the job red forever),
  and the reader answers it as no data. And **yfinance spells share classes with a
  dash** where this repo uses a dot — asked for `BRK.B` it answers that same empty
  shell for one of the largest companies there is — so `yahoo_symbol` asks for
  `BRK-B`, and a symbol whose dashed spelling is a shell is asked again as written
  (`ABC.L` is a London listing, not a share class). The row is keyed by the repo's
  symbol either way. Only a lookup that *raises* is a failure.
- **Orphans** — rows for symbols no fund lists as Untracked (promoted, or dropped
  by every fund) are deleted at the end of each run, which also covers a promotion
  made outside `complete_database.py`.
- **`--dry-run`** prints the plan and makes no yfinance call and no write — unlike
  `complete_database.py`'s, which does call yfinance — since a lookup is the
  expensive part and its outcome is the one thing a preview cannot show.

It exits 1 after the whole pass if any lookup failed, naming each symbol and its
reason. The table has to exist first (`sql/007`); until it does the first read
fails and the job is red.

## `add_ticker.py`

```bash
python scripts/add_ticker.py NVDA "AAPL:Apple Inc." --inactive
```

With a name, only `id`/`name`/`active` are set and the metadata columns stay null
until the next daily run backfills them. Without one, full live metadata is
looked up now.

Rows are upserted **one at a time**, not in a bulk call: named and unnamed
tickers produce different column sets, and PostgREST rejects a bulk payload whose
objects do not all share the same keys. Padding to a common key set would either
send nulls that clobber existing values on conflict, or require reasoning about
PostgREST's per-row column-default handling. Do not "optimise" this into one
call.

## Editing these scripts

- They print a per-ticker progress line and a summary, and `sys.exit(1)` on any
  failure so the GitHub Action goes red. Keep both.
- One bad symbol must never sink a batch — every per-item loop catches, records
  and continues.
- They are covered by `backend/tests/test_fetch_daily.py` and
  `test_complete_database.py`, which exercise `bucket_by_age`, `compact_ticker`,
  `_select_tickers_needing_sync`, `normalize_symbol`/`normalize_holdings` and
  `plan_tracking`/`complete_holdings` against fakes (`test_untracked_holdings.py`,
  whose double applies filters and writes, so a reader that forgets
  `.eq("tracked", True)` fails) — and `test_risk_free_rate.py`, which
  covers `fetch_risk_free_rate_rows`/`sync_risk_free_rate` the same way (issue
  #103) — and `test_fetch_run_record.py`, which runs `main()` itself against
  fakes to pin what the run record says and when it is written (issue #154) —
  and `test_untracked_metadata.py`, which reuses `test_untracked_holdings.py`'s
  double to pin the weekly lookup's plan, the demotion copy and the reader (issue
  #170).
  Add a case whenever you touch the
  bucketing or the escalation rules — they are the parts where a mistake corrupts
  stored data rather than failing loudly.
