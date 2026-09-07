/**
 * usePortfolioSimulation — what a portfolio would have been worth, kept
 * in step with the portfolio being edited.
 *
 * The simulation is the backend's (services/portfolio.py): weights are
 * normalised there, an allocation waits in cash until its holding lists,
 * and the metrics come back with the run. This hook is only responsible
 * for asking at a sensible moment.
 *
 * Typing a weight is a stream of intermediate portfolios, most of them
 * half-written, so the request is debounced: one simulation after the
 * typing stops rather than one per keystroke. `stale` says the numbers on
 * screen describe the portfolio as it was a moment ago, which lets the
 * table dim them instead of pretending they are current.
 *
 * A portfolio with nothing to invest — no holdings, or every weight zero
 * — is not simulated at all. The backend rejects it (rightly: there is no
 * portfolio there), and an error card in place of an empty table would be
 * a strange way to say "add something".
 */
import { useMemo } from 'react';
import { useDebouncedValue } from './useDebouncedValue';
import { useFetch } from './useFetch';
import { api } from '../utils/api';

/** Long enough to sit through a number being typed, short enough that
 *  pausing feels like the answer arriving rather than a wait. */
const SETTLE_MS = 400;

export function usePortfolioSimulation(portfolio) {
  // The request as a string, which is both the cache key and the payload:
  // useFetch's deps must be primitives, and deriving one from the other
  // keeps them from ever describing different portfolios.
  const requestKey = useMemo(() => {
    const holdings = (portfolio?.holdings || []).filter(h => h.weight > 0);
    if (holdings.length === 0) return '';
    return JSON.stringify({
      holdings: holdings.map(h => ({ ticker: h.ticker, weight: h.weight })),
      value: portfolio.value,
      rebalance: portfolio.rebalance,
    });
  }, [portfolio]);

  const settled = useDebouncedValue(requestKey, SETTLE_MS);

  const { data, loading, error, retry } = useFetch(
    (signal) => (settled ? api.simulatePortfolio(JSON.parse(settled), { signal }) : Promise.resolve(null)),
    [settled],
    { fallback: null }
  );

  return {
    simulation: settled ? data : null,
    loading: !!settled && loading,
    error: settled ? error : null,
    // True while the debounce is still holding an edit, so the caller can
    // show the previous run as provisional rather than as the answer.
    stale: requestKey !== settled,
    retry,
  };
}
