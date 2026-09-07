/**
 * useSimulationWindow — which stretch of history the portfolio is valued
 * over, held in the URL.
 *
 * The window belongs to the view rather than to the portfolio: the same
 * basket is worth looking at over the last year and over the last decade,
 * and neither reading is the portfolio's own property. So it lives in the
 * query string, the way the dashboard's fund and view live in the path —
 * a reload or a shared link reopens what the sender was looking at.
 *
 * Two shapes, because there are two kinds of answer:
 *
 *   ?window=ytd|1y|5y|max   a preset, which is relative to today and stays
 *                           relative — "the last year" means the last year
 *                           whenever the link is opened
 *   ?start=…&end=…          an exact window, which is absolute and does not
 *                           move
 *
 * A preset resolves to dates here, except **max**: how far back a basket
 * reaches is a fact about its holdings, so that one travels to the backend
 * as a period and comes back as the window it turned out to be.
 *
 * Anything unusable in the URL — a malformed date, an end before a start,
 * an end in the future, a preset that does not exist — falls back to the
 * default preset rather than erroring. A bad link should open the app, not
 * a complaint about itself.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';

/** Mirrors PERIOD_TO_DAYS in backend/config.py, so a preset asks for the
 *  same stretch the backend would have counted back itself. */
const DAYS = { '1y': 365, '5y': 1825 };

export const PRESETS = [
  { key: 'ytd', label: 'YTD' },
  { key: '1y', label: '1Y' },
  { key: '5y', label: '5Y' },
  { key: 'max', label: 'Max' },
];

export const DEFAULT_PRESET = '1y';

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function today() {
  return new Date().toISOString().slice(0, 10);
}

function shift(days) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

/** What a preset means in dates. `max` deliberately has none: the answer
 *  is in the data, not in the calendar. */
export function presetWindow(key) {
  if (key === 'max') return { period: 'max', start: null, end: null };
  if (key === 'ytd') return { start: `${new Date().getFullYear()}-01-01`, end: today() };
  return { start: shift(DAYS[key] ?? DAYS['1y']), end: today() };
}

/**
 * Why a window cannot be used, or null if it can. The same three rules
 * the backend applies (resolve_window), checked here so an unusable window
 * is a message rather than a request that comes back 400.
 */
export function windowProblem({ start, end }) {
  if (!start || !end) return null;
  if (!ISO_DATE.test(start)) return 'The start date is not a full date yet.';
  if (!ISO_DATE.test(end)) return 'The end date is not a full date yet.';
  if (start >= end) return 'The start date has to come before the end date.';
  if (end > today()) return 'The end date cannot be in the future.';
  return null;
}

export function useSimulationWindow() {
  const [params, setParams] = useSearchParams();

  const raw = {
    preset: params.get('window'),
    start: params.get('start'),
    end: params.get('end'),
  };

  const state = useMemo(() => {
    // An explicit window wins: it is the more specific statement, and it
    // is what the date inputs write.
    if (raw.start || raw.end) {
      const asked = { start: raw.start, end: raw.end };
      if (raw.start && raw.end && !windowProblem(asked)) {
        return { preset: null, ...asked };
      }
      // Unusable — fall through to the default rather than arguing.
    }
    const preset = PRESETS.some(p => p.key === raw.preset) ? raw.preset : DEFAULT_PRESET;
    return { preset, ...presetWindow(preset) };
  }, [raw.preset, raw.start, raw.end]);

  // A preset is a navigation worth going back from; retyping a date is
  // not, so the dates replace rather than pile up in history.
  const selectPreset = useCallback((key) => {
    setParams({ window: key });
  }, [setParams]);

  const setWindow = useCallback(({ start, end }) => {
    setParams({ start, end }, { replace: true });
  }, [setParams]);

  // Memoised because it is a fetch key downstream: rebuilt every render,
  // it would re-simulate on every render.
  const request = useMemo(
    () => (state.period ? { period: state.period } : { start: state.start, end: state.end }),
    [state]
  );

  return {
    /** The preset in force, or null when the window is an exact one. */
    preset: state.preset,
    /** What to send: `period` for max, otherwise `start`/`end`. */
    request,
    /** What to show in the date inputs. Null for max until a run reports
     *  the window it actually covered. */
    start: state.start,
    end: state.end,
    selectPreset,
    setWindow,
  };
}
