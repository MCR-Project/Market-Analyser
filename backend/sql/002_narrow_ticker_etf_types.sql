-- Narrow column types on ticker/etfs/etf_holdings where it's safe (issue #10).
--
-- Audited via information_schema + list_tables against the live project:
--   - ticker.market_cap is bigint and MUST stay that way — real market caps
--     (e.g. multi-trillion-dollar companies) exceed int4's ~2.1B range.
--   - etf_holdings.weight is an unbounded `numeric` storing a 0-100 percent
--     value already rounded to 2 decimals in application code
--     (services/market_data.py, scripts/fetch_daily.py) — `real` (float4,
--     ~7 significant digits) comfortably covers that range losslessly.
--   - Every other column (ticker.name/sector/currency/exchange/logo/website,
--     ticker.active, ticker.last_fetch, etfs.*) is already text/boolean/date
--     — nothing further to narrow.
--
-- Applied via Supabase's apply_migration; kept here for review/history.

alter table etf_holdings
    alter column weight type real;
