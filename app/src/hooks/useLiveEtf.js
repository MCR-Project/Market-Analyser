import { useMemo, useCallback } from 'react';
import { useFetch } from './useFetch';
import { api } from '../utils/api';
import { ETFS } from '../data/etfs';
import { useEtfStore } from '../store/useEtfStore';

/**
 * Fetches the currently selected ETF (per useEtfStore) plus the full ETF
 * list. Multiple components may call this independently — they all read
 * the same `etfId` from the shared store, so they never disagree on
 * which ETF is active even though each fetches its own copy of the data.
 */
export function useLiveEtf() {
  const etfId = useEtfStore((s) => s.etfId);
  const switchEtf = useEtfStore((s) => s.switchEtf);

  const mockEtf = useMemo(() => ETFS.find(e => e.id === etfId) || ETFS[0], [etfId]);

  const { data: liveEtf, loading, error } = useFetch(
    () => api.getEtf(etfId),
    [etfId],
    { fallback: null }
  );

  const etf = useMemo(() => {
    if (liveEtf && liveEtf.holdings?.length > 0) return liveEtf;
    return mockEtf;
  }, [liveEtf, mockEtf]);

  const tickers = useMemo(() => etf.holdings.map(h => h[0]), [etf]);

  const weightOf = useCallback((ticker) => {
    const h = etf.holdings.find(x => x[0] === ticker);
    return h ? h[1] : 0;
  }, [etf]);

  const combinedWeight = useMemo(() => etf.holdings.reduce((s, h) => s + h[1], 0), [etf]);

  const { data: allEtfs } = useFetch(
    () => api.listEtfs(),
    [],
    { fallback: ETFS }
  );

  return {
    etf, etfId, tickers, weightOf, combinedWeight, switchEtf,
    allEtfs: allEtfs || ETFS, loading, error,
    isLive: !!liveEtf && liveEtf.holdings?.length > 0,
  };
}
