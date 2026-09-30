-- Keep a fund's Untracked holdings listed instead of pruning them (issue #168,
-- docs/adr/0005-an-untracked-holding-stays-listed-with-no-prices.md).
--
-- A constituent weighing under 1% in every fund holding it used to be dropped:
-- never inserted, or deleted DB-wide together with its prices, dividends and
-- splits and its etf_holdings rows. A fund like SPY therefore kept ~46 of its
-- ~500 holdings, and the rest were recorded nowhere the backend could read, which
-- rules out ever reading the whole fund. From this migration on, such a holding
-- stays in etf_holdings with its weight and `tracked = false`, and loses only what
-- costs storage or a daily fetch (its ticker, prices, dividends and splits rows).
--
-- `tracked` is a fact about the STOCK - its highest weight across every fund
-- holding it clears the threshold, and it has a ticker row - and is written onto
-- every etf_holdings row of that stock in one pass by scripts/complete_database.py.
-- It is denormalised because an untracked stock has no ticker row to carry it, so
-- nothing but that script may write it, and it must always write all of a stock's
-- rows. Every existing row is a holding of a stock that has a ticker row, so the
-- default `true` is right for all of them and nothing needs backfilling: the
-- first completion run afterwards is what starts listing the light constituents.
--
-- The foreign key from etf_holdings.ticker to ticker.id is dropped, because an
-- untracked holding's ticker has no row to reference. That takes away the
-- database's own guarantee that a holding has a ticker behind it; the guarantee is
-- now "tracked = true implies a ticker row", held by complete_database.py
-- (plan_tracking flags a stock tracked only if the row exists) and by
-- fetch_daily.py's sync_etfs, which still skips live holdings it has no ticker for
-- - without that skip a new row would take the column default and read as tracked -
-- and which writes every row it touches with the flag its siblings already carry.
-- The other foreign key, to etfs.id, stays.
--
-- Every reader of etf_holdings now filters to `tracked` rows (get_etf_holdings, the
-- holdingCount in list_etf_summaries, sync_etfs), so nothing a fund shows changes.
-- Apply this BEFORE deploying the backend that filters on it: until the column
-- exists those reads error, and the holdings read falls back to yfinance's top ~10.
-- No index: the filter is applied inside reads that are already keyed on etf_id,
-- and the table is 319 rows today and a few thousand once the light constituents
-- of every tracked fund are listed.
--
-- Not applied when this file was written. Apply it via Supabase's apply_migration
-- before the first run of complete_database.py or fetch_daily.py that includes
-- this change; the file is kept here for review/history, like the ones before it.

alter table etf_holdings
    add column if not exists tracked boolean not null default true;

alter table etf_holdings
    drop constraint if exists etf_holdings_ticker_fkey;
