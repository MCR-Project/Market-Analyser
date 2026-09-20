import { useMemo } from 'react';
import { useFetch } from './useFetch';
import { api } from '../utils/api';
import { toCandles } from '../utils/candles';

const PERIOD_MAP = { '1W': '5d', '1M': '1mo', '1Y': '1y', '5Y': '5y' };

/**
 * Fetches a price series for `ticker` over `timeframe`.
 * Returns null for `arr`, `dates` and `candles` while the request is in
 * flight — consumers should check `loading` and render <Loading /> accordingly.
 *
 * `arr` and `dates` are the closes and their days, one per row the API
 * answered, and everything that is not a candle (the header return %, the
 * line) reads only those. `candles` (issue #152) is the same rows resampled
 * to one span per timeframe by `utils/candles.js`. It comes out of the one
 * request the line already made, so the candle view costs no second fetch and
 * can never disagree with the line about which window it is showing.
 */
export function useLiveSeries(ticker, timeframe = '1Y') {
  const period = PERIOD_MAP[timeframe] || '1y';

  const { data: liveData, loading } = useFetch(
    (signal) => api.getSeries(ticker, period, '1d', { signal }),
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

  const candles = useMemo(() => {
    if (liveData && liveData.length > 1) return toCandles(liveData, timeframe);
    return null;
  }, [liveData, timeframe]);

  return { arr, dates, candles, loading, isLive: !!liveData && liveData.length > 1 };
}
