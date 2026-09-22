# An untracked symbol on the Stock page is treated as a stock, never classified

The Stock page's search can open any symbol yfinance can price, not just the
tracked universe (`tickers.py`'s own `resolve_ticker` path, already used by
portfolio holdings). A tracked ETF match still routes to `/etf/:etfId`, but
anything resolved live and outside the tracked `etfs` table — a bond ETF, a
foreign fund, anything `resolve_ticker` returns with `kind: None` — opens on
the Stock page as though it were a company, with no attempt to detect what it
actually is first.

`resolve_ticker`'s own docstring already states the reason: "nothing in a live
lookup says whether this is a fund or a company... guessing would be worse
than saying so." yfinance's `.info` payload for an ETP is not a reliable
signal of that either — fields are inconsistently populated across share
classes and exchanges, and a false classification would send a real ETF to a
page built for a company, or the reverse, with no honest way to be sure. The
rare case of a niche ETF opening as a "Stock" page is a smaller cost than
fragile kind-detection logic breaking silently for something the rest of the
codebase already refuses to guess about.

## Considered options

- **Query yfinance's own `quoteType`/`info` fields to classify the symbol
  before routing.** Rejected: unreliable across instrument types and
  exchanges, and it would be a second, weaker classifier sitting beside
  `tickers.py`'s existing "tracked ETF vs. everything else" split — the two
  could disagree.
- **Refuse to open anything not already known to be a stock.** Rejected: it
  would defeat the point of letting the Stock page's search reach beyond the
  tracked universe at all, the same reasoning that already lets a portfolio
  hold any real ticker.
