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
 *   ?window=1m|3m|6m|1y|5y|ytd|max
 *                           a preset, which is relative to today and stays
 *                           relative — "the last year" means the last year
 *                           whenever the link is opened
 *   ?start=…&end=…          an exact window, which is absolute and does not
 *                           move
 *
 * A preset resolves to dates through `presetWindow` (`utils/windowPresets`),
 * except **max**: how far back a basket reaches is a fact about its holdings,
 * so that one travels to the backend as a period and comes back as the window
 * it turned out to be.
 *
 * Anything unusable in the URL — a malformed date, an end before a start,
 * an end in the future, a preset that does not exist — falls back to the
 * default preset rather than erroring. A bad link should open the app, not
 * a complaint about itself.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { withParams } from '../utils/searchParams';
import { windowProblem } from '../utils/windowCalendar';
import { DEFAULT_PRESET, PRESETS, presetWindow } from '../utils/windowPresets';

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

  // Both write through withParams rather than replacing the query: the
  // URL also carries what is being compared (#64), and changing the
  // period must not be a way to forget that.
  //
  // A preset is a navigation worth going back from; retyping a date is
  // not, so the dates replace rather than pile up in history.
  const selectPreset = useCallback((key) => {
    setParams(current => withParams(current, { window: key, start: null, end: null }));
  }, [setParams]);

  const setWindow = useCallback(({ start, end }) => {
    setParams(current => withParams(current, { start, end, window: null }), { replace: true });
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
