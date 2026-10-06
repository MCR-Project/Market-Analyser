import { useFetch } from './useFetch';
import { api } from '../utils/api';
import { useDeepFillEpoch } from './useDeepFillEpoch';

/** Shape returned before live data has arrived, or if the fetch never resolves. */
const EMPTY = { matrix: {}, tickers: [], averages: {}, weightedAverages: {}, strongest: null, weakest: null, hub: null, edgeCount: 0, clusters: [] };

/**
 * Fetches the pairwise correlation matrix (and derived stats: averages,
 * `weightedAverages` — the same average with each peer counting in
 * proportion to its fund weight, issue #185 — strongest/weakest pair, hub, and
 * `clusters` — the groups of holdings that moved together, issue #143) for an
 * ETF's holdings.
 *
 * Returns EMPTY placeholders while the request is in flight or if it
 * settles without live data — consumers should check `loading`/`isLive`
 * and render a loading indicator rather than assume the fields are
 * populated.
 */
export function useLiveCorrelation(etfId) {
  // The matrix covers the whole basket while the fund is deep-filled (issue #172).
  const deepFillEpoch = useDeepFillEpoch(etfId);
  const { data, loading, error } = useFetch(
    (signal) => api.getCorrelation(etfId, '1y', { signal }),
    [etfId, deepFillEpoch],
    { fallback: null }
  );

  const isLive = !!data?.matrix && Object.keys(data.matrix).length > 0;

  return {
    // `clusters: []` and `weightedAverages: {}` first, so a backend that predates
    // either field (a frontend deployed ahead of it) reads as "no groups" and "no
    // figure" rather than as undefined.
    ...(isLive ? { clusters: [], weightedAverages: {}, ...data } : EMPTY),
    loading,
    error,
    isLive,
  };
}
