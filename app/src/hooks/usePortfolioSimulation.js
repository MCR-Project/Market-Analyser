/**
 * usePortfolioSimulation — what a portfolio would have been worth, kept
 * in step with the portfolio being edited.
 *
 * The simulation is the backend's (services/portfolio.py): weights are
 * normalised there, an allocation waits in cash until its holding lists,
 * and the metrics come back with the run. This hook is only responsible
 * for asking at a sensible moment.
 *
 * Weight edits arrive already batched — the holdings table applies a
 * whole set at once — so the short debounce here is not absorbing a
 * keystroke storm. It collapses the bursts that are left: an amount
 * committed and a method changed in the same breath, or React's
 * development double-render, which would otherwise be two identical runs
 * of the same portfolio. `stale` says the numbers on screen describe the
 * portfolio as it was a moment ago, which lets the table dim them instead
 * of pretending they are current.
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

/** Short: every change reaching here is now a deliberate one, and making
 *  a deliberate action wait is just latency. Long enough to collapse two
 *  changes made in the same moment. */
const SETTLE_MS = 120;

export function usePortfolioSimulation(portfolio, windowRequest) {
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
      // Either a period or a start/end pair, never both - the backend
      // refuses the combination rather than picking one.
      ...(windowRequest || {}),
    });
  }, [portfolio, windowRequest]);

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
