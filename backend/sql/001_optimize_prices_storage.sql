-- Optimize `prices` table storage (issue #10).
--
-- prices is ~453MB (338MB table + ~115MB indexes) out of a ~500MB plan
-- limit, and 90%+ of the whole DB. This migration:
--   1. Creates sparse `dividends`/`splits` tables (only non-zero events),
--      replacing the dense `dividends`/`splits` columns on every price row.
--   2. Restructures `prices` to support tiered granularity: a `granularity`
--      column ('D'/'W'/'M') distinguishes daily rows from weekly/monthly
--      OHLC-resampled rows, since a coarse row's `date` is a bucket anchor
--      (Monday of the ISO week / 1st of the month), not one trading day.
--   3. Narrows numeric column types now that the table is being emptied
--      anyway (numeric -> real for prices, bigint -> integer for volume).
--   4. Truncates `prices` — old rows don't carry a `granularity` value and
--      mix daily data across all history; scripts/fetch_daily.py repopulates
--      everything under the new scheme on its next run.
--
-- Applied via Supabase's apply_migration; kept here for review/history.

-- ── Sparse dividends/splits tables ──────────────────────────────────────

create table if not exists dividends (
    ticker text not null references ticker(id),
    date date not null,
    dividends real not null,
    primary key (ticker, date)
);
alter table dividends enable row level security;

create table if not exists splits (
    ticker text not null references ticker(id),
    date date not null,
    splits real not null,
    primary key (ticker, date)
);
alter table splits enable row level security;

-- ── Restructure prices ──────────────────────────────────────────────────

truncate table prices;

alter table prices drop constraint prices_pkey;

alter table prices
    drop column dividends,
    drop column splits,
    add column granularity char(1) not null default 'D'
        check (granularity in ('D', 'W', 'M')),
    alter column open type real,
    alter column high type real,
    alter column low type real,
    alter column close type real,
    alter column volume type integer;

alter table prices add primary key (ticker, date, granularity);

-- Truncating `prices` alone isn't enough to trigger a real refill:
-- scripts/fetch_daily.py picks backfill vs top-up purely off whether
-- ticker.last_fetch is null, and every already-tracked ticker still has it
-- set from before this migration. Without this, the next run would only
-- pull a 5-day top-up per ticker and leave `prices` almost empty. Reset it
-- so every ticker gets a full backfill (tiered by age per bucket_by_age)
-- on the next run.
update ticker set last_fetch = null;
