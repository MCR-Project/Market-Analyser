/**
 * useRiskFreeRate — an optional override for the risk-free rate a run is
 * scored against, held in the URL (issue #103).
 *
 * The rate is an assumption about how a run is *scored* rather than a
 * property of the basket being run - the same argument that puts the
 * simulation window in the query string rather than in the portfolio
 * (useSimulationWindow.js) - so it lives in `?rf=` the same way: a reload
 * or a shared link reopens the same assumption rather than silently
 * defaulting.
 *
 * With no override (`?rf=` absent, or unusable - `?rf=abc`, empty, not a
 * finite number), `rate` is null and `request` is `{}`: the backend reads
 * the tracked series for the run's own window instead. A bad link should
 * open the app, not a complaint about itself - the same rule every other
 * URL-held selection here follows (App.jsx's view slug, useSimulationWindow's
 * preset, useMeasurementWindow's window).
 *
 * There is no visible control wired to this yet. No figure on screen
 * depends on the rate today - Sharpe and Sortino are filed separately
 * (issue #112) - and a control that changes nothing is clutter, not a
 * feature, the same reasoning TableView's MeasurementWindowControl is
 * built on (issue #101). This hook, and `request` merged into the
 * simulate payload in PortfolioPanel.jsx, are the plumbing #112's tiles
 * will read from and display next to their own figure - "whatever rate
 * produced a figure is shown next to it" is a per-figure display, not a
 * global one this hook should invent a placement for.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { withParams } from '../utils/searchParams';

export function useRiskFreeRate() {
  const [params, setParams] = useSearchParams();
  const raw = params.get('rf');

  const rate = useMemo(() => {
    if (raw === null || raw === '') return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }, [raw]);

  const setRate = useCallback((value) => {
    setParams(current => withParams(current, {
      rf: value === null || value === '' ? null : String(value),
    }));
  }, [setParams]);

  // Memoised because it feeds the simulate request downstream, the same
  // reason useSimulationWindow's own `request` is.
  const request = useMemo(() => (rate === null ? {} : { rate }), [rate]);

  return { rate, request, setRate };
}
