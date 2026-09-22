/**
 * StocksSidebar — the recently-viewed stocks, and a way to filter them
 * (issue #158, revised after the search bar moved to the main column).
 *
 *  ┌────────────────────┐
 *  │ [ filter history… ]│  ← pinned, never scrolls away
 *  ├────────────────────┤
 *  │ NVDA  NVIDIA       │  ↕ scrolls
 *  │ TSLA  Tesla        │
 *  │ …                  │
 *  └────────────────────┘
 *
 * This box does not call the API and cannot open a stock that isn't
 * already in `tickers` — it only narrows the list already on screen. The
 * search bar that actually switches stocks (resolving a symbol, possibly
 * one never viewed before) lives on the main page instead
 * (views/StockPage.jsx); this one exists purely to make a long history
 * navigable, the same distinction PortfolioSidebar draws between "open
 * this" and its own, separate compare toggle.
 *
 * Names beside each ticker come from a single batch lookup (api.getStocks)
 * rather than being stored — CONTEXT.md's Stock entry and
 * store/recentStocks.js both hold only the symbol, never a name that could
 * go stale sitting in localStorage.
 */
import { memo, useMemo, useState } from 'react';
import { NavLink } from 'react-router';
import { useFetch } from '../../hooks/useFetch';
import { api } from '../../utils/api';

export const StocksSidebar = memo(function StocksSidebar({ tickers }) {
  const [query, setQuery] = useState('');

  const { data: infos } = useFetch(
    (signal) => (tickers.length ? api.getStocks(tickers, { signal }) : Promise.resolve([])),
    [tickers.join(',')],
    { fallback: [] }
  );
  const nameOf = useMemo(
    () => Object.fromEntries((infos || []).map(info => [info.ticker, info.name])),
    [infos]
  );

  const normalized = query.trim().toUpperCase();
  const filtered = normalized
    ? tickers.filter(ticker => ticker.includes(normalized) || (nameOf[ticker] || '').toUpperCase().includes(normalized))
    : tickers;

  return (
    <nav aria-label="Recently viewed stocks" className="h-full flex flex-col gap-4 min-h-0">
      <input
        value={query}
        onInput={e => setQuery(e.target.value)}
        placeholder="Filter history…"
        aria-label="Filter recently viewed stocks"
        disabled={tickers.length === 0}
        className="w-full h-[38px] px-3 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-md)] text-[13px] text-[var(--fg)] outline-none focus:border-[var(--accent-ring)] disabled:opacity-50"
      />

      {tickers.length === 0 ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0 px-1 leading-relaxed">
          Nothing viewed yet.
        </p>
      ) : filtered.length === 0 ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0 px-1 leading-relaxed">
          No match in your history for "{query.trim()}".
        </p>
      ) : (
        <div className="corr-scroll flex-1 min-h-0 overflow-y-auto -mx-1 px-1">
          <ul className="list-none m-0 p-0 flex flex-col gap-0.5">
            {filtered.map(ticker => (
              <li key={ticker}>
                <NavLink
                  to={`/stock/${ticker}`}
                  className="block px-3 py-2 rounded-[var(--radius-sm)] no-underline transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] aria-[current=page]:bg-[var(--accent-soft)] hover:bg-[var(--bg-2)]"
                >
                  {({ isActive }) => (
                    <>
                      <div
                        className="font-[var(--font-mono)] text-[13px] font-bold leading-snug"
                        style={{ color: isActive ? 'var(--accent)' : 'var(--fg)' }}
                      >
                        {ticker}
                      </div>
                      <div className="text-[11.5px] leading-snug text-[var(--fg-2)] mt-0.5 truncate">
                        {nameOf[ticker] || ' '}
                      </div>
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      )}
    </nav>
  );
});
