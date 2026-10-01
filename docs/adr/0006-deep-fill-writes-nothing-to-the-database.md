# A Deep-fill writes nothing to the database; its result lives in the backend's memory

A Deep-fill fetches an Untracked holding's prices, volume and dividends from
yfinance at request time and keeps them — per ticker, plus one derived result per
fund (correlation matrix, clusters, the inputs to the Fund Index) — in the
backend's in-process cache, for `DEEP_FILL_TTL_SECONDS` and for at most
`DEEP_FILL_MAX_FUNDS` funds at once. Nothing is inserted into `prices`, `ticker`
or any other table. The one database fact about a deep-filled fund is the
`tracked` flag the weekly holdings job already maintains
(`0005-an-untracked-holding-stays-listed-with-no-prices.md`) and the descriptive
metadata that job stores; the Deep-fill only reads them.

The reason is what the alternative would commit the project to. Writing the tail
into `prices` makes it Tracked in all but name: the daily job would have to refresh
it or it would go stale and, by the Fund Index's own "complete history over the
window" rule, silently drop out of every fund-level number a week later — the fund
would quietly return to its pruned form. Refreshing it daily is the ~450-ticker
nightly cost that pruning exists to avoid, and the size of the database and of the
daily run would then depend on whether someone once pressed a button. A cache
expires by itself and says so.

The cost, accepted: the work is lost on a restart (`--reload` restarts on every
edit in development, and a free Render instance sleeps), and it must be paid again
for a fund after its lifetime ends. A Full view opened after that says the
Deep-fill has expired and offers to go back; it never draws a partial view. Every
cache that keys a fund-level answer on the fund alone (`fund_metrics`, the
correlation matrix) has to include whether the fund is deep-filled in its key, or
a pruned answer will be served for a deep-filled fund and the reverse.

## Considered options

- **Persist to `prices` and refresh daily** — rejected above: it makes the tail
  Tracked, with the daily cost and storage that implies.
- **Persist to `prices` and never refresh** — rejected: an aging tail drops out of
  the fund-level numbers without saying so, which is invariant 7 in reverse (a
  quietly missing figure read as complete).
- **A snapshot table, or a file on disk** — a restart would not lose the work, at
  the price of a schema or a format and a cleanup policy. Deferred, not rejected: it
  can be added behind the same cache interface if restarts prove too costly.
