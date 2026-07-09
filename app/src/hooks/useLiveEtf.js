import { useMemo, useCallback } from 'react';
import { useFetch } from './useFetch';
import { api } from '../utils/api';
import { useEtfStore } from '../store/useEtfStore';

/**
 * Fetches the currently selected ETF (per useEtfStore) plus the full ETF
 * list. Multiple components may call this independently — they all read
 * the same `etfId` from the shared store, so they never disagree on
 * which ETF is active even though each fetches its own copy of the data.
 *
 * `etf` is null until the API responds (and stays null on failure) —
 * consumers must gate on `loading`/`error` rather than assume it's set.
 */
export function useLiveEtf() {
  const etfId = useEtfStore((s) => s.etfId);
  const switchEtf = useEtfStore((s) => s.switchEtf);

  const { data: etf, loading, error, retry } = useFetch(
    () => api.getEtf(etfId),
    [etfId],
    { fallback: null }
  );

  const tickers = useMemo(() => etf?.holdings?.map(h => h[0]) ?? [], [etf]);

  const weightOf = useCallback((ticker) => {
    const h = etf?.holdings?.find(x => x[0] === ticker);
    return h ? h[1] : 0;
  }, [etf]);

  const combinedWeight = useMemo(
    () => etf?.holdings?.reduce((s, h) => s + h[1], 0) ?? 0,
    [etf]
  );

  const { data: allEtfs } = useFetch(
    () => api.listEtfs(),
    [],
    { fallback: null }
  );

  return {
    etf, etfId, tickers, weightOf, combinedWeight, switchEtf,
    allEtfs: allEtfs || [], loading, error, retry,
    isLive: !!etf?.holdings?.length,
  };
}
