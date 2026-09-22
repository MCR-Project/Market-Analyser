/**
 * AppLayout — the shell every page renders inside.
 *
 * Owns the one Header, so it is the same element across the dashboard and
 * the documentation rather than a lookalike rebuilt per page: the theme
 * is resolved once, and moving between pages doesn't unmount and repaint
 * the bar. Pages render into the Outlet below it and fill the remaining
 * height.
 *
 * It also remembers the last dashboard URL visited, so the "Analyser" tab
 * returns you to the fund and view you left rather than resetting to the
 * default ETF — and, the same way, the last Stock page visited, so the
 * "Stocks" tab returns to the ticker you left rather than an empty search
 * (issue #158). Unlike Analyser there is no default ticker to fall back to
 * (there is no equivalent of DEFAULT_ETF_ID for stocks — invariant 4 rules
 * out a hardcoded one), so the tab points at the bare `/stock` landing
 * state until something has actually been viewed.
 */
import { useMemo, useState } from 'react';
import { Outlet, useLocation } from 'react-router';
import { useTheme } from '../../hooks/useTheme';
import { useFreshness } from '../../hooks/useFreshness';
import { LiveStatusContext } from '../../hooks/useLiveStatus';
import { DEFAULT_ETF_ID } from '../../store/useEtfStore';
import { Header } from './Header';

export function AppLayout() {
  const { theme, toggleTheme } = useTheme('light');
  const { pathname, search } = useLocation();

  // Whichever page owns live data publishes it here for the badge.
  const [isLive, setIsLive] = useState(undefined);
  const liveStatus = useMemo(() => ({ isLive, publish: setIsLive }), [isLive]);

  // Unlike the badge above, freshness is a fact about the whole database, so
  // the layout reads it itself rather than have a page publish it — but only
  // once the app is on a page that reads prices. Docs shows no market data.
  const freshness = useFreshness(!pathname.startsWith('/docs'));

  // Remembered so the "Analyser" tab returns to the fund and view you
  // left, not the default ETF. Adjusted during render rather than in an
  // effect — see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  // — so the header never renders a tab pointing at the previous page.
  const [dashboardPath, setDashboardPath] = useState(`/etf/${DEFAULT_ETF_ID}`);
  const currentDashboardPath = pathname.startsWith('/etf/') ? pathname + search : null;
  if (currentDashboardPath && currentDashboardPath !== dashboardPath) {
    setDashboardPath(currentDashboardPath);
  }

  const [stockPath, setStockPath] = useState('/stock');
  const currentStockPath = pathname.startsWith('/stock') ? pathname + search : null;
  if (currentStockPath && currentStockPath !== stockPath) {
    setStockPath(currentStockPath);
  }

  return (
    <LiveStatusContext.Provider value={liveStatus}>
      <div className="h-screen overflow-hidden flex flex-col bg-[var(--bg)] text-[var(--fg-1)] font-[var(--font-body)]">
        <Header
          theme={theme}
          onToggleTheme={toggleTheme}
          isLive={isLive}
          freshness={freshness}
          dashboardPath={dashboardPath}
          stockPath={stockPath}
        />
        <Outlet />
      </div>
    </LiveStatusContext.Provider>
  );
}
