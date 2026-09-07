/**
 * Header — the bar shared by every page.
 *
 *  ┌──────────────────────────────────────────────────────────────────┐
 *  │ Market Analyser  Analyser | Portfolios | Docs  LIVE · returns ☀ │
 *  └──────────────────────────────────────────────────────────────────┘
 *
 * Three columns: the brand, the page tabs, and the status/theme controls.
 * The side columns are equal fractions and the middle is auto-width, so
 * the tabs sit centred in the bar however wide the brand or the controls
 * happen to be — and the columns shrink rather than overlap when there
 * isn't room.
 *
 * The connectivity badge is only rendered when a page has published a
 * status (see hooks/useLiveStatus): "LIVE · daily returns" is a claim
 * about the dashboard's data, and would be meaningless above the docs.
 */
import { Fragment, memo } from 'react';
import { Link, useLocation } from 'react-router';

const TAB_CLASS =
  'font-[var(--font-body)] text-sm no-underline px-3 py-1.5 rounded-[var(--radius-sm)] transition-colors duration-150 hover:bg-[var(--bg-3)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]';

function tabStyle(active) {
  return {
    color: active ? 'var(--fg)' : 'var(--fg-2)',
    fontWeight: active ? 700 : 500,
  };
}

export const Header = memo(function Header({
  theme,
  onToggleTheme,
  isLive,
  dashboardPath = '/',
}) {
  const { pathname } = useLocation();
  // Which tab is current is decided by the section of the app being
  // shown, not by an exact URL match — the dashboard has many URLs
  // (/etf/SMH/matrix and so on) and all of them are "Analyser", just as
  // every /portfolio/:id is "Portfolios".
  const section = pathname.startsWith('/docs')
    ? 'docs'
    : pathname.startsWith('/portfolio')
      ? 'portfolio'
      : 'analyser';

  return (
    // minmax(0,·) rather than plain 1fr: a grid track's default minimum is
    // its content, so the side columns would refuse to shrink and the brand
    // would run straight through the tabs on a narrow window.
    <header
      className="sticky top-0 z-40 flex-none h-[60px] grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-4 px-6 border-b border-[var(--border)]"
      style={{ background: 'color-mix(in oklab, var(--bg) 82%, transparent)', backdropFilter: 'blur(12px)' }}
    >
      {/* Stretched to its track rather than sized to its content, so the
          brand truncates inside the column instead of running past it. */}
      <div className="flex items-center gap-[11px] min-w-0">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--fg)] flex-none">
          <path d="M12 3c-2 2.6-2 5.4 0 8 2-2.6 2-5.4 0-8Z" />
          <path d="M12 11c-2.6-1.4-5.4-1.2-8 .4 2.2 2.2 5 2.6 8 1.1Z" />
          <path d="M12 11c2.6-1.4 5.4-1.2 8 .4-2.2 2.2-5 2.6-8 1.1Z" />
          <path d="M12 12.5V21" /><path d="M8.5 21h7" />
        </svg>
        <span className="font-extrabold tracking-tight text-[var(--accent)] text-[16px] whitespace-nowrap overflow-hidden text-ellipsis">Market Analyser</span>
      </div>

      <nav aria-label="Pages" className="justify-self-center flex items-center gap-1">
        {[
          { key: 'analyser', label: 'Analyser', to: dashboardPath },
          { key: 'portfolio', label: 'Portfolios', to: '/portfolio' },
          { key: 'docs', label: 'Docs', to: '/docs' },
        ].map((tab, i) => (
          <Fragment key={tab.key}>
            {i > 0 && <span aria-hidden="true" className="text-[var(--fg-3)] select-none">|</span>}
            <Link
              to={tab.to}
              aria-current={section === tab.key ? 'page' : undefined}
              className={TAB_CLASS}
              style={tabStyle(section === tab.key)}
            >
              {tab.label}
            </Link>
          </Fragment>
        ))}
      </nav>

      <div className="flex items-center justify-end gap-4 min-w-0">
        {/* A status line, not navigation — it steps aside on a narrow
            window rather than squeezing the tabs. */}
        {isLive !== undefined && (
          <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] flex-none hidden sm:flex items-center gap-1.5 whitespace-nowrap">
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: isLive ? 'var(--color-success)' : 'var(--color-warning)' }} />
            {isLive ? 'LIVE' : 'OFFLINE'} · daily returns
          </span>
        )}

        <button
          onClick={onToggleTheme}
          aria-label="Toggle theme"
          className="flex-none w-[38px] h-[38px] grid place-items-center bg-[var(--bg-3)] border border-[var(--border)] rounded-[var(--radius-md)] text-[var(--fg-1)] cursor-pointer"
        >
          {theme === 'light' ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></svg>
          )}
        </button>
      </div>
    </header>
  );
});
