# backend/services — data access and arithmetic

Six modules, and the large ones carry most of the project's load-bearing
decisions.

| Module | Responsibility |
| --- | --- |
| `supabase_client.py` | Client construction, and the pagination rules every read must follow |
| `cache.py` | Process-local TTL dict, one shared singleton |
| `market_data.py` | Every read of ETF/stock/price/dividend data: DB first, live yfinance fallback, cached |
| `tickers.py` | The tracked universe (search) and resolving one symbol outside it |
| `stats.py` | Return and risk arithmetic over a plain series — no I/O, shared by `portfolio.py` and every future single-holding metric |
| `portfolio.py` | The simulation — decides what series to hand `stats.py` and assembles its answers into a portfolio's shape, no I/O of its own beyond the reads it calls |

## The pattern every `market_data` function follows

1. Check the TTL cache.
2. Try Supabase. On a miss (no row, or a not-yet-synced sentinel) or **any**
   error, fall back to a live yfinance call through `_live(...)`.
3. Cache the result — skipping failures — and return.

The private `_..._live` helpers are the original all-yfinance implementations,
kept exception-transparent because `scripts/` calls them directly and wants the
real upstream error. `_live()` is the only wrapper that converts a failure into
`SymbolNotFound` (upstream said 404) or `DataUnavailable` (anything else); see
`backend/CLAUDE.md` for why those two must never be collapsed.

An upstream 429 is a third case (issue #92): `_live()` starts
`_rate_limit_cooldown` (a `_RateLimitCooldown`, module-level singleton like
`cache` above) and every call answers `DataUnavailable` without touching
yfinance again until it expires, reporting the real time left as
`retry_after` rather than the usual 3. Deliberately not part of `cache.py`'s
TTL dict — it stores no answer, just the one process-wide fact that yfinance
is throttling this process right now, which is what a *request* can be keyed
by but a rate limit cannot: it applies to every call, not one. A test that
triggers this (a 429, or a bare `YFRateLimitError`) must patch
`services.market_data._rate_limit_cooldown` with a fresh instance — the real
one is a genuine 60-second timer, and leaving it running leaks into whatever
test runs next in the same process.

`_upstream_status` walks the exception's `__cause__`/`__context__` chain and
trusts `response.status_code` over `code`, because curl_cffi sets `code` to 0
even on a genuine 404.

Sentinels worth knowing:

- `_get_stock_info_db` treats **`sector IS NULL`** as "never synced" and returns
  a miss. All six metadata columns are always written together, so a null sector
  cannot mean anything else.
- `get_etf_holdings` returns `(holdings, stale)` as one tuple, cached together.
  `stale` means the holdings came from the live top-~10 fallback rather than the
  full DB constituent list. It is deliberately not a sibling cache key — two
  concurrent requests for the same ETF could interleave and read one without the
  other.

## Supabase reads

`paginated_select(build_query)` takes a **zero-argument callable returning a
fresh builder**, not a builder. postgrest-py's `.range()` *adds* offset/limit
params rather than replacing them, so re-ranging one builder accumulates stale
params instead of advancing. Always give the query a deterministic `ORDER BY`,
ideally over a unique key — `.range()` paging re-issues a separate query per
page, and without a stable sort Postgres may skip or duplicate rows at page
boundaries.

`assert_not_truncated(rows)` is for a read you are confident stays far under the
1000-row cap: it raises if the result came back at exactly the cap, turning a
future silent truncation into a loud failure.

`get_client_optional()` never raises and memoises **only success**. A failed
construction is retried next call, because the first attempt on a cold process
can fail for reasons that say nothing about the config (DNS, a cold TLS
handshake) — latching that failure silently demoted every later request to the
yfinance fallback until someone restarted the server. `get_client()` (which does
raise) is for scripts, which should hard-fail on missing config.

## Price frames: `get_closes`

The shared reader for anything needing several tickers priced over one window.
One query for the whole basket, pivoted into a wide `date × ticker` frame with a
tz-naive `DatetimeIndex` on both paths — the DB path pivots ISO strings and
yfinance hands back timestamps, and a caller doing date arithmetic must not read
a different type depending on which answered.

`min_tickers` is how wide the frame has to be before the DB counts as having
answered: correlation needs a pair (default 2), a portfolio of one holding does
not (the simulator passes 1).

**A partial answer is the dangerous case.** `_closes_db` is satisfied once it has
`min_tickers` columns, so one tracked stock was enough to keep an ETF — which has
no `prices` rows, since ETFs live in `etfs` — out of the frame entirely. An
absent column is not read downstream as "no data"; the simulator read it as a
holding that had not listed yet and valued it at zero for the whole run
(issue #86). So `get_closes` now completes a partial answer: the missing columns
are fetched live and merged onto the DB frame's own calendar.

`_onto_calendar` is the part to be careful with. A bucket's `close` is its
**last** close but its `date` is its **anchor**, so "the last live value at or
before each anchor" takes the close from *before* the bucket began and puts the
merged column a whole bucket behind. Each anchor instead takes the last live
close **inside its own bucket**, from the anchor up to the next one; daily rows
are the same rule with one-row buckets. The known cost of the merge is that a
holding aligned onto a coarse calendar is sampled as coarsely as its
basket-mates, so it reports slightly less volatility than it would on its own
daily rows.

`_merge_missing_live` deliberately does **not** wrap its live read in a `try` — a
non-existent symbol should still 404 and an unreachable upstream should still
503, exactly as when the whole basket goes live.

## Dividends

`get_dividends` reads the sparse `dividends` event table — one row per ex-date
per ticker, holding the cash amount **as declared and deliberately unadjusted**.
`prices` carries adjusted closes, so the return already includes these; adjusting
them again would count the same money twice.

There is **no live fallback** here, on purpose: a number that sometimes comes
from a record and sometimes from a network call is a number nobody can
reconcile. A ticker with no events in the window is *absent* from the result
rather than present with an empty list, so the caller has to decide what absence
means. `tracked_tickers()` is how it decides — a ticker with a row in `ticker`
that paid nothing genuinely reports `0`; one with no row at all (every ETF, and
anything resolved live) reports `null`.

## `tickers.py` — two questions, two paths

- **"What can I pick?"** → `search_tickers`, answered entirely from a cached
  snapshot of `ticker` + `etfs`. This is the as-you-type path: it never calls
  yfinance and never touches the network per keystroke. Ranking is
  symbol-exact → symbol-prefix → symbol-contains → name-start → word-in-name.
  A name never matches mid-word, or two keystrokes of "NV" pull up Invesco QQQ.
- **"Is this real, and can we price it?"** → `resolve_ticker`, asked once, for a
  symbol somebody has actually chosen. The test is **price history, not a name**:
  yfinance answers a made-up ticker's info request with a shell dict, so a name
  proves nothing. Returns `firstDate`, which is what lets the UI warn that a
  holding will sit in cash for part of a window.

ETFs are written into the universe map *after* stocks, so a symbol somehow in
both tables reads as the fund it is. A tracked ETF has no `prices` rows of its
own, so its `firstDate` comes from live history — that is the normal answer, not
a fault.

## `stats.py` — the shared return and risk arithmetic

Pure arithmetic over a plain series (a list of values and, wherever time
matters, a list of ISO dates the same length): no I/O, and no imports from
`market_data`, `supabase_client` or `yfinance` — that is what lets a future
single-holding measurement call it directly instead of reaching past
`services/market_data` the way `backend/CLAUDE.md`'s layering table forbids
(issue #98). `portfolio.py` is its first and, so far, only caller.

The module docstring states the conventions once — **a year is 365.25 days;
volatility (and anything built from the same scaled returns — downside
deviation, beta, idiosyncratic volatility) annualises to 252 trading days,
each return first divided by the root of the trading time its own gap
covers; a coarse row is a bucket, not a day** — and every other module,
including this one's own function docstrings, references it rather than
restating it. That scaling is not a refinement: a real 2019–2026 basket
spanning all three storage tiers (issue #10) reported 54% volatility
without it against a true 35%. `granularity_of` names the coarsest gap a
computation actually saw ('D'/'W'/'M', the same letters a `prices` row's
own granularity uses), and the functions whose answer depends on it —
volatility, downside deviation, max drawdown, the underwater/pain-index
pair, beta, R², idiosyncratic volatility, the capture ratios — carry it
alongside their value; CAGR does not, because the entire point of counting
elapsed days instead of rows is that its answer must not depend on how
finely the window was sampled.

`herfindahl`/`effective_n` (concentration of a set of weights) and
`risk_contribution` (each holding's share of portfolio variance, an Euler
decomposition) are the two exceptions to the "returns a value plus its
granularity" shape: the first two have no time dimension at all, and the
third already returns one figure per ticker.

A figure a series cannot support is `None` everywhere in this module, never
0 — a two-row series has a return but no volatility, and reporting 0 would
claim it was riskless rather than simply short.

## `portfolio.py` — the model

The module docstring is the full statement of the model; `README.md`'s
"Portfolio simulator" section is the same material for readers. **Any change
to the arithmetic has to update both**, and a change to the return/risk
arithmetic itself belongs in `stats.py` above, not here. The invariants:

- **Weights are ratios and are normalised.** 30/30/30 and 33.33/33.33/33.33 are
  the same portfolio and must simulate identically. Negative weights are refused
  outright — coercing −5 to either 5 or 0 invents an intention nobody expressed.
- **Buy and hold by default.** A rebalance restores the target weights on the
  **first row of each new period**, never on a fixed calendar date: the 1st is
  often not a trading day, and an old enough window has no daily rows at all.
  Contributions land on exactly the same definition, and never on the window's
  own first row (that one is the opening lump sum).
- **An allocation is cash until its holding lists**, and converts at exactly that
  day's close, so the total does not move on the day it happens.
- **The calendar is the union of the dates the rows cover, not the
  intersection.** A gap inside a holding's own history is forward-filled; the
  dates before its first close stay empty, which is what keeps it cash.
- **Time-weighted vs money-weighted is the point.** Total return, CAGR,
  volatility and drawdown are read off `stats.unit_values` — the total with
  deposits taken back out — and describe the portfolio. `moneyWeightedReturn`
  (IRR by bisection, still computed here — it is about the account's own cash
  flows, not shared with a single holding) describes the account. With no
  contributions `units` *is* `totals`, by identity, which is what makes "off by
  default" a promise: a run without contributions is not merely close to the
  old result, it is the same object.
- **A holding's `contribution` is its final value less every dollar put into
  it.** Once a rebalance moves money between holdings, a final value says nothing
  about which holding earned it. These sum to the portfolio's gain. The UI labels
  the column GAIN to avoid colliding with recurring contributions.
- **Dividend income is reported, never added.** It is already inside every value
  via the adjusted closes.
- **A figure the run cannot support is `null`, not `0`.** `metrics.reasons`
  (issue #99) says why, for whichever of `cagr`/`volatility`/
  `moneyWeightedReturn` actually is — the same optional sidecar shape a
  measurement column's `per_ticker_reason` is, present only when at least
  one metric in this particular run is null, so a normal multi-row run
  gets back exactly the response it always has.

`_verify_absent` is where three identical-looking situations are told apart. An
absent price column means either a typo (→ `SymbolNotFound`, 404), a holding that
had not listed yet (→ cash, the normal case), or a holding whose resolved
`firstDate` predates the window and therefore *should* have priced (→
`DataUnavailable`, 503, because the read failed). Do not simplify this back into
two cases.

`MAX_HOLDINGS = 50` bounds the price read one anonymous request can ask for
(issue #93) — measured against a real 512MB-capped container, not primarily a
memory concern (a 32-year, 100-holding run peaked at 174MB), but latency and
CPU cost per request from a caller who has proven nothing about who they are.
`MONEY_DP`
rounds each holding's value and sums the total from those rounded parts, so a
stacked chart's bands add up to exactly the total line drawn above them —
computing the total independently would leave them a cent apart.
