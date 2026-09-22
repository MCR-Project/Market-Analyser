/**
 * StocksSidebar — the always-present way to switch stocks (issue #158),
 * and the shortlist of ones recently looked at.
 *
 *  ┌────────────────────┐
 *  │ [ search a stock ] │  ← pinned, never scrolls away
 *  ├────────────────────┤
 *  │ NVDA  NVIDIA       │  ↕ scrolls
 *  │ TSLA  Tesla        │
 *  │ …                  │
 *  └────────────────────┘
 *
 * Shaped like PortfolioSidebar/DocsSidebar: one pinned control above a
 * scrolling list. `tickers` (from store/recentStocks.js, via
 * hooks/useRecentStocks) holds only symbols, never a name or logo that
 * could go stale sitting in `localStorage` — this reads them fresh through
 * the same batch stock lookup (`api.getStocks`) StockPopup already uses to
 * label its peer cards, so a company that changed its name shows the
 * current one rather than whatever was true the day it was first opened.
 *
 * Picking a search result is handled by the caller (`onResolved`), not
 * here — resolving a tracked ETF instead of a stock has to navigate
 * somewhere this sidebar has no route to (docs/adr/0004).
 */
import { memo, useMemo } from 'react';
import { NavLink } from 'react-router';
import { TickerSearchField } from '../portfolio/TickerSearchField';
import { useFetch } from '../../hooks/useFetch';
import { api } from '../../utils/api';

export const StocksSidebar = memo(function StocksSidebar({ tickers, onResolved }) {
  const { data: infos } = useFetch(
    (signal) => (tickers.length ? api.getStocks(tickers, { signal }) : Promise.resolve([])),
    [tickers.join(',')],
    { fallback: [] }
  );
  const nameOf = useMemo(
    () => Object.fromEntries((infos || []).map(info => [info.ticker, info.name])),
    [infos]
  );

  return (
    <nav aria-label="Stocks" className="h-full flex flex-col gap-4 min-h-0">
      <TickerSearchField
        placeholder="Search a stock…"
        ariaLabel="Search for a stock"
        onResolved={onResolved}
      />

      {tickers.length === 0 ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0 px-1 leading-relaxed">
          Nothing viewed yet.
        </p>
      ) : (
        <div className="corr-scroll flex-1 min-h-0 overflow-y-auto -mx-1 px-1">
          <ul className="list-none m-0 p-0 flex flex-col gap-0.5">
            {tickers.map(ticker => (
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
