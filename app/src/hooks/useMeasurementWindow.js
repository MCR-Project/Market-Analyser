/**
 * useMeasurementWindow — the shared window every window-aware measurement
 * column is computed over, held in the URL (issue #101).
 *
 * One control for the whole table, not one per column: two window-aware
 * columns must never describe different periods (a "1Y" volatility next
 * to a "5Y" one would be two different claims wearing the same header),
 * so there is exactly one value here rather than one per measurement. A
 * column with no window (every official one, today) ignores this
 * entirely - see useMeasurements.js, which is what actually decides,
 * per column, whether to send it.
 *
 * Lives in the query string the same way the fund and the view do
 * (issue #101's decision, mirroring how the portfolio simulator's own
 * window already works in useSimulationWindow.js): a reload or a shared
 * link reopens the same window rather than silently defaulting.
 *
 * WINDOW_OPTIONS/DEFAULT_WINDOW mirror MEASUREMENT_WINDOW_OPTIONS /
 * MEASUREMENT_WINDOW_DEFAULT in backend/config.py — keep the two in
 * step. Values are yfinance-style periods ("1y", "5y", ...), the same
 * vocabulary PERIOD_TO_DAYS uses, so a window-aware plugin can pass one
 * straight through to a price read without translating it.
 *
 * An unusable value in the URL — an old link naming a retired option, a
 * typo — falls back to the default rather than erroring, the same rule
 * every other URL-held selection in this app follows (App.jsx's view
 * slug, useSimulationWindow's preset): a bad link should open the app,
 * not a complaint about itself.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { withParams } from '../utils/searchParams';

export const WINDOW_OPTIONS = [
  { value: '3mo', label: '3M' },
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1Y' },
  { value: '5y', label: '5Y' },
  { value: 'max', label: 'Max' },
];

export const DEFAULT_WINDOW = '1y';

/** The display label for a window value, or the value itself if it names
 *  no known option — mirrors MeasurementBase.window_label on the backend. */
export function windowLabel(value) {
  return WINDOW_OPTIONS.find(o => o.value === value)?.label ?? value;
}

export function useMeasurementWindow() {
  const [params, setParams] = useSearchParams();
  const raw = params.get('window');

  const window_ = useMemo(
    () => (WINDOW_OPTIONS.some(o => o.value === raw) ? raw : DEFAULT_WINDOW),
    [raw]
  );

  const setWindow = useCallback((value) => {
    setParams(current => withParams(current, { window: value }));
  }, [setParams]);

  return { window: window_, setWindow };
}
