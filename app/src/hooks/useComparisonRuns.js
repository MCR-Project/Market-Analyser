/**
 * useComparisonRuns — one simulation per line on the comparison chart.
 *
 * Every line is a run of the same endpoint over the same window: a
 * portfolio as it stands, or a benchmark as a basket of one ticker. That
 * sameness is the point — a benchmark gets its return, CAGR, volatility
 * and drawdown from exactly the code that produced the portfolio's, so
 * the summary table is comparing like with like rather than one number
 * computed two ways.
 *
 * The runs are fetched together but settled apart: a benchmark whose
 * ticker upsets the price source should cost the chart that one line, not
 * every line. Each entry comes back with either a simulation or the error
 * that stopped it.
 */
import { useMemo } from 'react';
import { useDebouncedValue } from './useDebouncedValue';
import { useFetch } from './useFetch';
import { api } from '../utils/api';

/** Matches usePortfolioSimulation: deliberate changes only, so this is
 *  about collapsing a burst rather than absorbing typing. */
const SETTLE_MS = 120;

/**
 * `lines` is [{ key, label, kind, request }] where request is a simulate
 * payload. Returns the same list with `simulation` / `error` attached.
 */
export function useComparisonRuns(lines) {
  // One key for the whole set: the chart is a single answer made of
  // several requests, and a line changing shape means the answer changed.
  const requestKey = useMemo(() => JSON.stringify(lines.map(line => line.request)), [lines]);
  const settled = useDebouncedValue(requestKey, SETTLE_MS);

  const { data, loading, error, retry } = useFetch(
    async (signal) => {
      const requests = JSON.parse(settled || '[]');
      if (requests.length === 0) return [];
      const results = await Promise.allSettled(
        requests.map(request => api.simulatePortfolio(request, { signal }))
      );
      return results.map(result =>
        result.status === 'fulfilled'
          ? { simulation: result.value, error: null }
          : { simulation: null, error: result.reason }
      );
    },
    [settled],
    { fallback: null }
  );

  const runs = useMemo(() => {
    // Results are positional, so a stale set (one line longer than the
    // one on screen) is not merged - it would attach a run to the wrong
    // line for a frame.
    if (!data || data.length !== lines.length) return null;
    return lines.map((line, i) => ({ ...line, ...data[i] }));
  }, [data, lines]);

  return {
    runs,
    loading: loading || requestKey !== settled,
    error,
    stale: requestKey !== settled,
    retry,
  };
}
