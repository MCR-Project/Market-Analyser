-- Track a risk-free rate series, for Sharpe/Sortino (issue #103).
--
-- A single fixed rate would be meaningfully wrong over the windows this app
-- can already simulate: short rates moved from roughly zero to five percent
-- between 2020 and 2026, and a ratio computed against the wrong rate is
-- wrong by exactly that gap. So the rate is tracked like everything else
-- the pipeline tracks, in its own table, refreshed daily by
-- scripts/fetch_daily.py alongside prices/dividends/splits - never a
-- hardcoded figure in application code.
--
-- risk_free_rate_source names *which* upstream symbol backs the tracked
-- series - invariant 4 ("no hardcoded ticker list anywhere") applies to
-- this series too, so scripts/fetch_daily.py reads which symbol to fetch
-- from here rather than from a Python constant, the same way which ETFs
-- are tracked is a fact about the `etfs` table rather than code (see
-- "How something enters the universe" in backend/scripts/CLAUDE.md).
-- Seeded once below with the 13-week Treasury bill discount rate - the
-- standard short-term risk-free proxy - by hand, in SQL, not by any
-- script; changing it later is a database edit, not a deploy. At most one
-- row is meaningful (out of scope: more than one rate), but nothing here
-- enforces that beyond convention - there is no product reason to track
-- two.
--
-- risk_free_rate is one row per trading day the pipeline could read a
-- yield for, unlike `prices`: there is no OHLCV here to bucket by age, so
-- there is nothing to compact and no `granularity` column. `rate` is a
-- yield, stored exactly as read - a percentage per annum, not a price -
-- so none of `prices`' adjusted-close rules apply to it.
--
-- Applied via Supabase's apply_migration; kept here for review/history.

create table if not exists risk_free_rate_source (
    symbol text primary key
);
alter table risk_free_rate_source enable row level security;

insert into risk_free_rate_source (symbol) values ('^IRX')
    on conflict (symbol) do nothing;

create table if not exists risk_free_rate (
    date date primary key,
    rate real not null
);
alter table risk_free_rate enable row level security;
