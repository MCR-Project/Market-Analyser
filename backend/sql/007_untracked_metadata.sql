-- Descriptive data for Untracked holdings, refreshed weekly (issue #170,
-- docs/adr/0005-an-untracked-holding-stays-listed-with-no-prices.md and
-- docs/adr/0006-deep-fill-writes-nothing-to-the-database.md).
--
-- An Untracked stock (issue #168) keeps its etf_holdings rows and nothing else:
-- no ticker row, so no name, sector or market cap. A Deep-fill (issue #171) reads
-- a fund's tail live for prices, volume and dividends, but sector and market cap
-- would cost one slow yfinance `.info` call per stock - ~450 for SPY - on every
-- Deep-fill, and those figures change slowly. So the weekly holdings job stores
-- one row per Untracked stock here, and a Deep-fill only reads it. Prices are not
-- stored; this table is descriptive data and nothing that costs a daily fetch.
--
-- Same descriptive columns as `ticker`, with the same types, plus:
--   checked_at  when the row was last looked up or copied; the weekly job skips a
--               row checked within the last 7 days, so this is what keeps a
--               re-run from calling yfinance again.
--   failure     why the last lookup failed, null when it succeeded. A failed
--               lookup keeps its row (so the symbol is retried next week and the
--               reader can say why it has no answer) and leaves the descriptive
--               columns as they were, so a stock that once had data and has a
--               bad week does not lose it - the reader simply declines to use a
--               row that carries a failure.
-- There is no `active` and no `last_fetch`: nothing here is fetched daily.
--
-- Rows come and go with a stock's own standing, written by two scripts:
--   scripts/complete_database.py   demotion COPIES the stock's `ticker` metadata
--                                  here before deleting its ticker row (no
--                                  `.info` call), and a stock that is Tracked has
--                                  any row here deleted.
--   scripts/sync_untracked_metadata.py   looks up every Untracked symbol that has
--                                  no row or an old one, and deletes rows for
--                                  symbols no fund lists as Untracked any more.
-- There is deliberately no foreign key to `ticker` (the symbol has none) or to
-- `etf_holdings` (its ticker column is not unique); those two scripts keep it
-- honest, the way sql/006 left the Tracked promise to code.
--
-- No index and no pagination concern beyond the ordinary: the table holds one row
-- per Untracked symbol (~450 for SPY, a few thousand across a total-market fund)
-- and every reader reads it by primary key. RLS is enabled with no policies, like
-- every other table here: only the backend's service key can read or write it.
--
-- Applied via Supabase's apply_migration; kept here for review/history. Apply it
-- BEFORE the first run of complete_database.py or sync_untracked_metadata.py that
-- includes this change, or the demotion copy is skipped with a warning and the
-- weekly step errors on its first read.

create table if not exists untracked_metadata (
    id text primary key,
    name text,
    sector text,
    market_cap bigint,
    currency text,
    exchange text,
    logo text,
    website text,
    checked_at timestamptz not null default now(),
    failure text
);
alter table untracked_metadata enable row level security;
