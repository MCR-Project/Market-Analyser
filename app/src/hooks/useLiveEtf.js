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
    (signal, force) => api.getEtf(etfId, { refresh: force, signal }),
    [etfId],
    { fallback: null }
  );

  // Bypasses the backend cache outright (see /api/etf's `refresh` param) -
  // for the "this looks stale/incomplete" manual refresh action, where
  // waiting out the normal retry()'s cache hit wouldn't help.
  const forceRefresh = useCallback(() => retry(true), [retry]);

  const tickers = useMemo(() => etf?.holdings?.map(h => h[0]) ?? [], [etf]);

  const weightOf = useCallback((ticker) => {
    const h = etf?.holdings?.find(x => x[0] === ticker);
    return h ? h[1] : 0;
  }, [etf]);

  const { data: allEtfs } = useFetch(
    (signal) => api.listEtfs({ signal }),
    [],
    { fallback: null }
  );

  return {
    etf, etfId, tickers, weightOf, switchEtf,
    allEtfs: allEtfs || [], loading, error, retry, forceRefresh,
    isLive: !!etf?.holdings?.length,
  };
}
