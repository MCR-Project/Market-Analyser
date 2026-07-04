import { useMemo } from 'react';
import { useFetch } from './useFetch';
import { api } from '../utils/api';

const PERIOD_MAP = { '1W': '5d', '1M': '1mo', '1Y': '1y', '5Y': '5y' };

/**
 * Fetches a price series for `ticker` over `timeframe`.
 * Returns null for `arr` and `dates` while the request is in flight —
 * consumers should check `loading` and render <Loading /> accordingly.
 */
export function useLiveSeries(ticker, timeframe = '1Y') {
  const period = PERIOD_MAP[timeframe] || '1y';

  const { data: liveData, loading } = useFetch(
    () => api.getSeries(ticker, period),
    [ticker, period],
    { fallback: null }
  );

  const arr = useMemo(() => {
    if (liveData && liveData.length > 1) return liveData.map(p => p.close);
    return null;
  }, [liveData]);

  const dates = useMemo(() => {
    if (liveData && liveData.length > 1) return liveData.map(p => p.date);
    return null;
  }, [liveData]);

  return { arr, dates, loading, isLive: !!liveData && liveData.length > 1 };
}
