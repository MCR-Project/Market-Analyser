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
 * default ETF.
 */
import { useMemo, useState } from 'react';
import { Outlet, useLocation } from 'react-router';
import { useTheme } from '../../hooks/useTheme';
import { LiveStatusContext } from '../../hooks/useLiveStatus';
import { DEFAULT_ETF_ID } from '../../store/useEtfStore';
import { Header } from './Header';

export function AppLayout() {
  const { theme, toggleTheme } = useTheme('light');
  const { pathname, search } = useLocation();

  // Whichever page owns live data publishes it here for the badge.
  const [isLive, setIsLive] = useState(undefined);
  const liveStatus = useMemo(() => ({ isLive, publish: setIsLive }), [isLive]);

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

  return (
    <LiveStatusContext.Provider value={liveStatus}>
      <div className="h-screen overflow-hidden flex flex-col bg-[var(--bg)] text-[var(--fg-1)] font-[var(--font-body)]">
        <Header
          theme={theme}
          onToggleTheme={toggleTheme}
          isLive={isLive}
          dashboardPath={dashboardPath}
        />
        <Outlet />
      </div>
    </LiveStatusContext.Provider>
  );
}
