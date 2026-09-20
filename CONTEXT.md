# Market Analyser

ETF correlation dashboard and portfolio simulator. One glossary covers both
halves — the tracked-universe / measurement side (holdings, correlation,
measurements) and the stateless simulation side (portfolios, runs, metrics) —
since the repo is developed as a single context and the two halves share
vocabulary (`weight`, `window`, `holding`) throughout.

## Language

### The tracked universe

**Tracked**:
A ticker with its own row in the `ticker` table: full price history, and
weighs at least 1% (`--min-weight`) in at least one ETF that holds it. This is
a DB-wide property, not a per-ETF one — a stock is only pruned when its
*highest* weight across every ETF holding it falls below the threshold, so a
stock at 0.4% in one ETF stays tracked as long as it clears 1% in any other.
Stocks added by hand (`scripts/add_ticker.py`) belong to no ETF and are never
pruned regardless of weight.
_Avoid_: Listed, covered

**ETF** (a.k.a. **Fund**):
A tracked, holdings-bearing instrument in the `etfs` table. "Fund" is used
interchangeably with "ETF" throughout formulas and prose ("fund weight",
"fund index", "fund metrics") — there is no broader or narrower sense, and no
other instrument type (e.g. mutual funds) exists in this app.
_Avoid_: Index (for the instrument itself — see Fund Index below for the
one place "index" means something specific)

**Holding**:
A ticker and a weight inside a basket. Two unrelated baskets use the word: an
ETF's real-world constituent (tracked in Supabase, has an `etf_holdings`
weight) and an entry in a simulated portfolio (an arbitrary ticker, lives only
in the browser, no relation to any ETF). Context — which page, which basket —
always says which is meant; the word is deliberately not split further. An
ETF can itself appear as a holding inside another ETF, in which case it has
no `prices` rows of its own to compute volume from.
_Avoid_: Constituent, Position (as separate terms for the two senses —
deliberately not used)

**Weight**:
A ratio describing a holding's share of a basket. Three qualified senses
appear: a user's target allocation for a portfolio holding (normalised,
non-negative), a real constituent's position size inside an ETF ("fund
weight", the wᵢ in the correlation/risk-contribution formulas), and the
hypothetical weight a passive, cap-weighted basket would give a holding ("cap
weight", used only for Cap-Weight Tilt). One glossary entry; the qualifier in
front tells you which.
_Avoid_: Allocation (for the portfolio sense — "weight" is used even there)

### Correlation

**Correlation**:
ρ between two return series. This app names it at two scopes: **AVG ρ**, the
pairwise average across an ETF's whole holdings basket (shown on the identity
card), and **Correlation to Fund**, one holding's ρ against the fund's own
weighted-return index (a holdings-table measurement). Same underlying
statistic, different inputs — not split into separate terms.
_Avoid_: Basket Correlation, Fund Correlation (as separate terms)

**Fund Index**:
An ETF's own weighted-return series, built once from whichever tracked
holdings have a complete price history over the window (weights renormalised
to sum to 100%, so the untracked share isn't treated as cash earning
nothing). The shared benchmark every holding-relates-to-fund measurement
(Correlation to Fund, Beta, Tail Correlation, Capture, Rolling Correlation)
reads.
_Avoid_: Benchmark (reserved for the portfolio-simulator sense, below — a
fund index is never user-chosen)

**Cluster**:
A group of two or more Holdings of one ETF whose returns moved together over
the correlation matrix's fixed one-year lookback — not a Window the user picks:
groups are joined while their members average at least the Cluster Level in ρ
to each other. A statement about how prices moved, not about what the
companies do, and not a forecast. A holding in no Cluster is simply in none;
it is not a "cluster of one". Named after its heaviest Holding by fund weight
("NVDA group"), the same in every view that shows it.
_Avoid_: Group (bare), Segment; Sector, which classifies what a company does,
not how its price moved

**Cluster Level**:
The average ρ two groups of holdings must reach for the clustering to join
them into one Cluster. A level of correlation, not a number of clusters, so a
fund whose holdings all move together is not forced to split.
_Avoid_: Threshold (bare — see Link Threshold, a different number that
decides which *pairs* connect, not which groups merge), Cutoff

**Link**:
A pair of holdings drawn joined in the network view because their ρ is at
least the Link Threshold. It says only that the pair's ρ cleared a bar the
user set — not that either holding is in a Cluster, or that the two share one.
_Avoid_: Edge, Line (the wire field `edgeCount` and the code say "edge", and
the legend says "line"; neither is the term)

**Link Threshold**:
The minimum ρ a pair of holdings needs for the network view to draw a Link
between them, set by the user with a slider. The only number in this app
called a threshold; not the Cluster Level, which decides which *groups* of
holdings merge.
_Avoid_: Edge threshold, Cutoff

**Others**:
In the correlation matrix's cluster order, the holdings that have history but
no Cluster block to sit in *on screen*: they joined no Cluster, or their
Cluster has only this one member among the holdings shown. A display grouping
only — the holding's real Cluster is unchanged.
_Avoid_: Unclustered (it would say the holding is in no Cluster, which is not
always true), Singletons

**No History**:
A holding whose ρ against every peer is unknown, because it shares too little
overlapping history with any of them. Not the same as uncorrelated: a low ρ
says something, no history says nothing. Kept apart from Others for exactly
that reason.
_Avoid_: Uncorrelated, Unclustered

### Measurements and metrics

**Measurement**:
A self-contained plugin computing one or more holdings-table columns for a
fund's constituents (e.g. Correlation to Fund, Volatility, Dividend Yield).
Lives in `backend/measurements/`, documented at `/docs/<measurement id>`.
_Avoid_: Metric (reserved for the portfolio/fund-run sense, below)

**Metric**:
A self-contained plugin computing one portfolio-summary tile, keyed either to
a completed Run (`portfolio` family = time-weighted, or `account` family =
money-weighted) or to a fund as a whole (`computed_from: "etf_id"`, e.g.
Diversification Ratio). Lives in `backend/portfolio_metrics/`, documented at
`/docs/<metric id>`.
_Avoid_: Measurement

**Dividend Yield**:
A holdings-table measurement: trailing-twelve-months declared dividends ÷ the
holding's last close. Not the same figure as Portfolio Dividend Yield below
despite the shared name — different denominator, different window.
_Avoid_: none for this entry — always say "Portfolio Dividend Yield" for the
other one, never leave "Dividend Yield" to mean it by default

**Portfolio Dividend Yield**:
A portfolio metric (`metrics.dividendYield`): dividend income earned during a
Run ÷ that Run's Paid In. Computed over the simulation's own window,
not a fixed trailing twelve months.
_Avoid_: Dividend Yield (bare — ambiguous with the measurement above)

**Risk Contribution**:
A holding's own share of a fund's variance (Euler decomposition, summing to
100% across the fund). Appears both as a holdings-table measurement and as
the shared arithmetic behind the fund metric "variance share of the top
five."
_Avoid_: Contribution (bare) — see Recurring Contribution and Gain below for
why that word alone is never safe here

### Portfolio simulation

**Portfolio**:
A saved, named basket: tickers, weights, an amount, a rebalance method, and
an optional Recurring Contribution or Recurring Withdrawal schedule (never
both). Lives only in the browser
(`localStorage`, key `market-analyser.portfolios`) — there is no server-side
portfolio and never will be: with only a Supabase service key and no
sign-in, a server-side table would be one shared, world-editable list.
_Avoid_: Account

**Run**:
One execution of a Portfolio (or a Benchmark, or a Share Link's payload)
against a window, priced and scored by `POST /api/portfolio/simulate`.
Non-durable — exists only in the response. A Portfolio produces a different
Run every time its window, rate, or Recurring Contribution or Recurring
Withdrawal changes.
_Avoid_: Simulation (used loosely elsewhere in prose; "Run" is the noun for
one concrete result)

**Benchmark**:
A ticker plotted alongside Portfolios for comparison (`?benchmark=`).
Deliberately not a Portfolio: it's simulated as a basket of one, given the
open portfolio's own amount and Money Flow (whichever schedule it has), and
never touches the portfolio library.
_Avoid_: Fund Index (reserved for the ETF-side benchmark series, above)

**Recurring Contribution**:
A schedule (`{amount, frequency}`) that pays money into a Portfolio's Run
periodically, on the first row of each new period after the start. Off by
default — an absent, null, or zero contribution simulates identically to a
single lump sum. A Portfolio has this or a Recurring Withdrawal, never both.
_Avoid_: bare "Contribution" — always say "recurring"; Increment,
Incrementation

**Recurring Withdrawal**:
A schedule (`{amount, frequency}`) that takes a fixed dollar amount out of a
Portfolio's Run periodically, on the first row of each new period after the
start — the same timing rule as a Recurring Contribution, with no way to
start it later. Each withdrawal comes out of every holding (and any cash still
waiting for a holding to list) in proportion to what each is worth at that
moment, so it changes how much the Portfolio holds and leaves its drifted mix
alone. When the Portfolio cannot cover a withdrawal it gives up whatever is
left and pays nothing after that; the Run says when it ran out. Off by
default. Not a sale of the Portfolio and not a Rebalance — money leaves the
Portfolio rather than moving between its holdings.
_Avoid_: Scheduled Withdrawal, Decumulation; bare "Withdrawal" when it could
be read as a one-off

**Money Flow**:
The one choice a Portfolio makes about money after its opening amount: pay in
on a schedule (a Recurring Contribution), draw out on a schedule (a Recurring
Withdrawal), or neither — never both. It is what the editing control is called;
the two schedules are the terms everything else uses.
_Avoid_: Cash flow (a return-arithmetic word for every signed payment in a Run,
the opening amount and the closing value included), bare "Schedule"

**Paid In**:
Every dollar that ever went into a Run: the opening amount plus every Recurring
Contribution (API field `totalInvested`, labelled PAID IN in the UI). Never
reduced by a Recurring Withdrawal — money taken out is its own figure,
Withdrawn — so it only ever grows, and a Portfolio drawn on for longer than it
was funded does not report a negative amount paid in. What a Run's Gain and
Portfolio Dividend Yield are measured against.
_Avoid_: Total Invested (that's the wire field name, not the glossary term), Net
invested (it would let the figure go negative)

**Gain**:
The dollar amount of a Run's total gain attributable to one holding (API
field `contribution`, labelled GAIN in the UI) — that holding's final value,
plus every dollar a Recurring Withdrawal took out of it, less every dollar put
into it. Money spent is still money earned, so a withdrawal never shrinks a
Gain. Per-holding gains sum to the portfolio's own.
_Avoid_: Contribution (that's the wire field name, not the glossary term)

**Share**:
A holding's percent of a finished Run (API field `share`) — how much of the
portfolio's ending value that holding makes up. Distinct from Income Share (a
measurement: dividend income relative to a holding's own total return) and
from Share Link (below) — three unrelated uses of the same English word.
_Avoid_: assuming it means Income Share or Share Link without checking context

**Share Link**:
A read-only URL encoding a Portfolio's full definition
(`/portfolio/shared?p=<payload>`), with no server-side storage. Opens a Run
exactly like a saved Portfolio but with every write control removed; "Save a
copy" is what turns it into a real, independent Portfolio.
_Avoid_: Shared Portfolio — the link doesn't hold a portfolio, it holds the
payload to reconstruct a Run

**Backup**:
A JSON file holding one Portfolio or many, with everything each one has —
identity and dates included — so they can leave a browser (**Export**) and be
added to a library elsewhere (**Import**). It is the owner's own copy, not a
preview for somebody else: unlike a Share Link it carries no view state (window,
benchmark) and it arrives as ordinary saved Portfolios, not read-only. Importing
only ever adds; it never replaces or deletes a Portfolio already saved.
_Avoid_: Restore (it suggests putting back over what is there, which Import never
does), Share Link (a different thing — a definition for someone else to look at)

**Window**:
The stretch of history a view is computed over — set via `?window=` (a
preset like `1y`, or an explicit `start`/`end`) for a portfolio Run, or via
the holdings table's own window control for window-aware Measurements.
"Period" is only the backend request-body field name for the same concept.
_Avoid_: Period, except when naming that specific API field

**Rebalance**:
Restoring a Portfolio's target Weights from its then-current total, on the
first row of each new month/quarter/year (never a fixed calendar date). The
alternative, and the default, is Buy and Hold — weights bought once, then
left to drift.
_Avoid_: none
