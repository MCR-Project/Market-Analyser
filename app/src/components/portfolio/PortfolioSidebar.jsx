/**
 * PortfolioSidebar — the saved portfolios, and the way to make another.
 *
 * Shaped like DocsSidebar, with one structural difference that is the
 * whole point: **Create** sits outside the scrolling list, not at the top
 * of it. A list long enough to scroll would otherwise carry the button
 * off the top of the panel exactly when there are enough portfolios to
 * want another one.
 *
 *  ┌────────────────────┐
 *  │ + New portfolio    │  ← pinned, never scrolls away
 *  ├────────────────────┤
 *  │ Semis, equal weight│  ↕ scrolls
 *  │ 12 holdings        │
 *  │ Copy of SPY        │
 *  │ 28 holdings        │
 *  └────────────────────┘
 *
 * A row is a link plus one control: the toggle that puts that portfolio
 * on the chart beside the open one. Renaming, duplicating and deleting
 * live on the open portfolio's own panel rather than on every row —
 * with thirty portfolios, three controls each is thirty times the clutter
 * for an action taken once in a while — but comparing is a thing you do
 * *from* the list, to a portfolio you are not currently looking at, so it
 * has to be here.
 */
import { memo } from 'react';
import { NavLink } from 'react-router';

const CURRENCY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

function describe(portfolio) {
  const count = portfolio.holdings?.length || 0;
  const holdings = count === 0 ? 'No holdings' : count === 1 ? '1 holding' : `${count} holdings`;
  return `${holdings} · ${CURRENCY.format(portfolio.value)}`;
}

export const PortfolioSidebar = memo(function PortfolioSidebar({
  portfolios,
  onCreate,
  openId,
  comparedIds,
  onToggleCompare,
  comparisonFull,
}) {
  const compared = new Set(comparedIds || []);
  return (
    // The column, not its contents, owns the height: the button is
    // flex-none and the list is the only thing that scrolls.
    <nav aria-label="Portfolios" className="h-full flex flex-col gap-4 min-h-0">
      <button
        onClick={onCreate}
        className="flex-none flex items-center justify-center gap-2 h-[38px] px-3 bg-[var(--accent-soft)] border border-[var(--accent-ring)] rounded-[var(--radius-md)] text-[var(--accent)] font-semibold text-[13px] cursor-pointer transition-colors duration-150 hover:bg-[var(--accent-ring)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
        New portfolio
      </button>

      {portfolios.length === 0 ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0 px-1 leading-relaxed">
          No portfolios yet.
        </p>
      ) : (
        <div className="corr-scroll flex-1 min-h-0 overflow-y-auto -mx-1 px-1">
          <ul className="list-none m-0 p-0 flex flex-col gap-0.5">
            {portfolios.map(portfolio => {
              const isOpen = portfolio.id === openId;
              const isCompared = compared.has(portfolio.id);
              return (
              <li key={portfolio.id} className="relative group">
                <NavLink
                  to={`/portfolio/${portfolio.id}`}
                  className="block px-3 py-2 rounded-[var(--radius-sm)] no-underline transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] aria-[current=page]:bg-[var(--accent-soft)] hover:bg-[var(--bg-2)]"
                >
                  {({ isActive }) => (
                    <>
                      <div
                        className="text-[13.5px] leading-snug truncate"
                        style={{
                          color: isActive ? 'var(--accent)' : 'var(--fg)',
                          fontWeight: isActive ? 700 : 500,
                        }}
                      >
                        {portfolio.name}
                      </div>
                      <div className="text-[11.5px] leading-snug text-[var(--fg-2)] mt-0.5">
                        {describe(portfolio)}
                      </div>
                    </>
                  )}
                </NavLink>
                {onToggleCompare && !isOpen && (
                  <button
                    onClick={() => onToggleCompare(portfolio.id)}
                    aria-pressed={isCompared}
                    disabled={comparisonFull && !isCompared}
                    title={
                      isCompared
                        ? `Stop comparing ${portfolio.name}`
                        : comparisonFull
                          ? 'The chart is full'
                          : `Compare ${portfolio.name} with the open portfolio`
                    }
                    className="absolute top-1.5 right-1.5 w-6 h-6 grid place-items-center rounded-[var(--radius-sm)] border cursor-pointer transition-opacity duration-150 disabled:opacity-30 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--accent)]"
                    style={{
                      // Out of the way until it is wanted, but never
                      // hidden from a keyboard: focus brings it back.
                      opacity: isCompared ? 1 : undefined,
                      background: isCompared ? 'var(--accent-soft)' : 'var(--bg-1)',
                      borderColor: isCompared ? 'var(--accent-ring)' : 'var(--border)',
                      color: isCompared ? 'var(--accent)' : 'var(--fg-2)',
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      {isCompared ? <path d="M20 6 9 17l-5-5" /> : <path d="M12 5v14M5 12h14" />}
                    </svg>
                  </button>
                )}
              </li>
              );
            })}
          </ul>
        </div>
      )}
    </nav>
  );
});
