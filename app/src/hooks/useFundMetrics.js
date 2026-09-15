/**
 * useFundMetrics — the fund-level metric registry (issue #105): which of
 * the computed_from="etf_id" portfolio-metric entries are active, and
 * their real values for the currently active ETF.
 *
 * Two independent fetches, unlike usePortfolioMetrics: the manifest
 * (fetched once, from the same /api/portfolio-metrics endpoint, filtered
 * down to the etf_id-scoped entries) and, per etfId, the actual figures —
 * there is no already-in-hand response to read a fund metric's value out
 * of the way a portfolio metric reads simulate_portfolio()'s.
 *
 * `?fundMetrics=` is its own query-string key (issue #105's own
 * decision), read/written through searchParams.js's readList/withParams
 * exactly like every other multi-value URL param here — never by
 * replacing the whole query string — so it can never collide with the
 * portfolio page's own `?metrics=` even though both hold a comma-
 * separated id list.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { useFetch } from './useFetch';
import { api } from '../utils/api';
import { readList, withParams } from '../utils/searchParams';

export function useFundMetrics(etfId) {
  const [params, setParams] = useSearchParams();

  const {
    data: manifestData,
    loading: manifestLoading,
    error: manifestError,
    retry: retryManifest,
  } = useFetch((signal) => api.listPortfolioMetrics({ signal }), [], { fallback: null });

  const families = manifestData?.families || {};
  const tileMetrics = useMemo(
    () => (manifestData?.metrics || []).filter(m => m.computed_from === 'etf_id' && m.tile),
    [manifestData]
  );

  const activeIds = useMemo(() => {
    const known = new Set(tileMetrics.map(m => m.id));
    const fromUrl = readList(params, 'fundMetrics').filter(id => known.has(id));
    if (fromUrl.length > 0) return fromUrl;
    return tileMetrics.filter(m => m.default_enabled).map(m => m.id);
  }, [params, tileMetrics]);

  const toggle = useCallback((id) => {
    const known = new Set(tileMetrics.map(m => m.id));
    const current = readList(params, 'fundMetrics').filter(x => known.has(x));
    const base = current.length > 0
      ? current
      : tileMetrics.filter(m => m.default_enabled).map(m => m.id);
    const next = base.includes(id) ? base.filter(x => x !== id) : [...base, id];
    setParams(p => withParams(p, { fundMetrics: next.length ? next.join(',') : null }));
  }, [params, setParams, tileMetrics]);

  const {
    data: valuesData,
    loading: valuesLoading,
    error: valuesError,
    retry: retryValues,
  } = useFetch(
    (signal) => (etfId ? api.getFundMetrics(etfId, { signal }) : Promise.resolve(null)),
    [etfId],
    { fallback: null }
  );

  const retry = useCallback(() => { retryManifest(); retryValues(); }, [retryManifest, retryValues]);

  return {
    tileMetrics,
    families,
    activeIds,
    toggle,
    isActive: (id) => activeIds.includes(id),
    values: valuesData?.values || {},
    reasons: valuesData?.reasons || {},
    loading: manifestLoading || valuesLoading,
    error: manifestError || valuesError,
    retry,
  };
}
