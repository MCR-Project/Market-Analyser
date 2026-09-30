# An Untracked holding stays listed with its weight and no prices; `tracked` is a flag on `etf_holdings`

A fund's constituent that weighs under 1% in every ETF holding it used to be
dropped: never inserted, or deleted DB-wide together with its prices, dividends
and splits. It is now kept as an `etf_holdings` row with `tracked = false`, holding
its weight and nothing else that costs storage or a daily fetch. `tracked` is a fact
about the *stock* (highest weight across every ETF holding it clears the
threshold), written onto every row for that stock in one pass by
`complete_database.py`; it is not a per-fund fact, so a stock at 0.4% in one fund
and 2% in another stays Tracked, and stays in the first fund's view, exactly as it
does today.

This exists so that a Deep-fill can be told *what to fetch*: the full constituent
list of a fund such as SPY is otherwise thrown away at the door, and the only
other copy is a provider scrape the backend cannot run (Playwright and Chromium,
in a GitHub Action). The flag lives on `etf_holdings` rather than `ticker`
because an Untracked stock has no `ticker` row, so the foreign key from
`etf_holdings.ticker` to `ticker.id` is dropped. Demoting a stock still deletes its
`ticker`, `prices`, `dividends` and `splits`, so the database stays as small as it
is now; only its weight row and a row of descriptive metadata remain (see the
Untracked metadata table, refreshed weekly by the holdings job).

The cost is that **every reader of `etf_holdings` must now filter to tracked
rows** — `get_etf_holdings`, the `holdingCount` in `market_data.py`, `sync_etfs`
and the prune stage — or a fund's default view jumps from ~46 holdings to ~500.
The denormalised flag can also disagree between two rows of the same stock if
anything writes one row without the other; only the completion script writes it,
and always for all of a stock's rows at once.

## Considered options

- **A separate table of Untracked holdings** — no flag, no foreign-key change, no
  filter on existing readers. Rejected: a stock crossing 1% would move between two
  tables on every weekly run, and "the whole fund" would need a union that every
  reader could forget.
- **A per-pair flag (`weight ≥ 1%` in that fund)** — simpler to compute, but it
  would silently remove from a fund's view every stock that is Tracked only because
  another fund holds it more heavily, changing numbers for funds nobody asked to
  change.
- **Keep pruning and re-scrape at Deep-fill time** — rejected: it needs a browser
  in the backend image, which neither the Render free tier nor the live demo has.
