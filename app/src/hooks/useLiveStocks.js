import { useMemo } from 'react';
import { useFetch } from './useFetch';
import { api } from '../utils/api';

/**
 * Batch-fetches metadata (name, sector, …) for a list of tickers and
 * exposes it as a ticker-keyed map. Consumers should treat a missing
 * entry as "not loaded yet / unknown" and render a placeholder rather
 * than assume every ticker resolves.
 */
export function useLiveStocks(tickers) {
  const { data, loading, error } = useFetch(
    () => (tickers.length ? api.getStocks(tickers) : Promise.resolve([])),
    [tickers.join(',')],
    { fallback: null }
  );

  const stockMap = useMemo(
    () => Object.fromEntries((data || []).map(s => [s.ticker, s])),
    [data]
  );

  return { stockMap, loading, error };
}
