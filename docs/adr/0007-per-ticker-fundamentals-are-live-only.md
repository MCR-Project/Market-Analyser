# Trailing/forward P/E, profit margin, ownership, earnings growth, debt and revenue per share are live-only, with no Supabase column

Issue #194 added eight per-ticker figures — trailing and forward P/E, profit
margin, held % insiders, held % institutions, earnings quarterly growth, total
debt and revenue per share — read straight from `yf.Ticker(...).info` by
`services.market_data.get_stock_fundamentals`. Unlike Market Cap, which the
`ticker` table carries and `scripts/fetch_daily.py` keeps in sync, none of these
eight has a database column at all: every read is a live yfinance call, cached
in-process at `CACHE_TTL_HOLDINGS` like any other per-ticker metadata lookup,
and nothing writes a row anywhere.

The reason is how often each one actually changes. Trailing and forward P/E move
with every price tick — the denominator is fixed between earnings releases, but
the numerator is today's quote — and the other six move once a quarter, at each
earnings release. A once-a-day pipeline sync would be stale for the first case
before the day is out and would add a sync for six fields that change roughly
twelve times a year, for a page that reads them "once in a while" (the same
phrase `get_stock_description`'s own docstring uses, and the same reasoning:
this is prose and a handful of numbers that move too often to be worth carrying
through a daily job, not a second source anybody reconciles against the first).

The cost, accepted: a holding whose column is enabled in the table, or a Stock
page that is opened, pays a live `.info` call per ticker rather than reading a
synced row — the same cost `get_stock_description` and `get_listing_currency`
already accept for the same reason, bounded by the existing `CACHE_TTL_HOLDINGS`
TTL rather than a new one.

**Issue #195 extended this to four more reads**: a stock's quarterly balance
sheet, quarterly cash flow, six-month insider-purchases summary and top-10
institutional holders (`get_stock_balance_sheet`, `get_stock_cash_flow`,
`get_stock_insider_purchases`, `get_stock_institutional_holders`) — whole
statements and tables, not single `.info` fields, but the same reasoning
applies even more plainly: nothing in this app's own pipeline has ever carried
a balance sheet or a holders list, these change at most once a quarter, and
only the Stock page reads any of them. Same TTL, same no-DB-column choice, no
new considered options beyond the two below.

## Considered options

- **Add columns to `ticker` and sync them in `scripts/fetch_daily.py`** —
  rejected: P/E would be a day stale by the time of the next close, and the other
  six would be unchanged for eleven syncs out of twelve between earnings — cost
  with no freshness to show for it.
- **A separate `fundamentals` table, refreshed weekly like
  `untracked_metadata`** — deferred, not rejected: if the live-call cost ever
  proves too high (rate-limit pressure, a heavily-used column), this can be
  added behind `get_stock_fundamentals`'s own interface without moving the
  measurements or the Stock page that read it.
