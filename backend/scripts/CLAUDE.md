# backend/scripts — the data pipeline

Three scripts maintain the tracked universe in Supabase. All are run from
`backend/` and need `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in `.env`. None of
them is imported by the running service; they reach past `market_data`'s caching
layer into its private `_*_live` helpers on purpose, because they are what makes
the DB fresh — a DB-first read here would write the same rows back in a circle.

| Script | Job | Trigger |
| --- | --- | --- |
| `add_ticker.py` | Add or update tickers by hand | manual |
| `complete_database.py` | Complete tracked ETFs from a provider holdings JSON | `fetch-holdings.yml` (manual dispatch) |
| `fetch_daily.py` | Refresh prices, metadata and ETF holdings for everything tracked | `fetch-daily.yml` (cron, 22:30 UTC Mon–Fri) |

## How something enters the universe

An ETF is tracked by having a row in `etfs` — inserted by hand through the
Supabase dashboard or SQL. Nothing in this repo adds one. `complete_database.py`
then fills in its metadata, its constituent tickers and their price history from
a holdings JSON produced by a `fetcher/` scraper; `fetch_daily.py` keeps
everything fresh from then on.

A stock enters either as a constituent weighing at least **1%** of a covered ETF
(`MIN_HOLDING_WEIGHT_PCT`), or by hand via `add_ticker.py`. Below the threshold a
holding is never inserted, and an existing one is **pruned** DB-wide when it is
below the threshold in *every* ETF that holds it. Stocks held by no ETF at all
(hand-added watchlist entries) are never pruned.

## `fetch_daily.py`

Five phases, in order:

1. **`sync_etfs`** — refresh `etfs` metadata and `etf_holdings` weights for every
   ETF in the DB. The DB rows are the full constituent list and the source of
   truth; yfinance only exposes the top ~10, so the live call refreshes the
   weights it knows about and **never shrinks** the DB set. Empty fields from
   yfinance are left out of the upsert so a flaky response cannot blank values
   the completion script already filled. Holdings for untracked tickers are
   skipped (`etf_holdings.ticker` has an FK to `ticker.id`), not failed.
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
5. **`compact_ticker`** — sweep every known ticker (active or not) and promote
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

`_select_tickers_needing_sync` returns every active ticker **plus** any inactive
one whose `last_fetch` is null. That second half exists so a prices-convention
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
backfill new tickers above the weight threshold, upsert the full holdings, then
prune everything DB-wide that fell below the threshold.

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
- Pruning follows FK order — `etf_holdings`, `prices`, `dividends`, `splits`,
  then the `ticker` row.
- `PRICE_UPSERT_CHUNK = 5000`, because a `max` backfill can exceed 10k rows.

Every write is an upsert keyed on the primary key, so a second run finds 0 new
tickers and changes nothing. Use `--dry-run` first when in doubt.

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
  `prune_below_threshold` against fakes. Add a case whenever you touch the
  bucketing or the escalation rules — they are the parts where a mistake corrupts
  stored data rather than failing loudly.
