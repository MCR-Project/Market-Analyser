import { useFetch } from './useFetch';
import { api } from '../utils/api';

/** Shape returned before live data has arrived, or if the fetch never resolves. */
const EMPTY = { matrix: {}, tickers: [], averages: {}, strongest: null, weakest: null, hub: null, edgeCount: 0 };

/**
 * Fetches the pairwise correlation matrix (and derived stats: averages,
 * strongest/weakest pair, hub) for an ETF's holdings.
 *
 * Returns EMPTY placeholders while the request is in flight or if it
 * settles without live data — consumers should check `loading`/`isLive`
 * and render a loading indicator rather than assume the fields are
 * populated.
 */
export function useLiveCorrelation(etfId, tickers, threshold = 0) {
  const { data, loading, error } = useFetch(
    () => api.getCorrelation(etfId, '1y', threshold),
    [etfId, threshold],
    { fallback: null }
  );

  const isLive = !!data?.matrix && Object.keys(data.matrix).length > 0;

  return {
    ...(isLive ? data : EMPTY),
    loading,
    error,
    isLive,
  };
}
