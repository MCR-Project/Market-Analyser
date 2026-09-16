/**
 * usePortfolioRisk — the portfolio-risk registry (issue #113): which of
 * the computed_from="risk" entries are active, and their real values for
 * the basket currently open.
 *
 * Mirrors useFundMetrics' shape almost exactly (manifest fetched once,
 * filtered to its own computed_from; real figures fetched separately) but
 * with one deliberate difference: the figures are fetched **only once
 * some risk tile is actually switched on**. A correlation matrix over the
 * basket is a second, wider price read than a run needs, and issue #113's
 * own reasoning for giving it its own endpoint - not folding it into
 * `simulate` - is exactly to avoid paying for that read on every
 * portfolio, including the ones nobody has asked a risk question of.
 * `request` is `null` (rather than an empty object) whenever there is
 * nothing to simulate at all (see PortfolioPanel's own `simulateRequest`),
 * which this hook also treats as "nothing to fetch".
 *
 * `?risk=` is its own query-string key, the same "never collide" rule
 * `usePortfolioMetrics`'s `?metrics=` and `useFundMetrics`'s
 * `?fundMetrics=` already follow.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { useFetch } from './useFetch';
import { api } from '../utils/api';
import { readList, withParams } from '../utils/searchParams';

export function usePortfolioRisk(request) {
  const [params, setParams] = useSearchParams();

  const {
    data: manifestData,
    loading: manifestLoading,
    error: manifestError,
    retry: retryManifest,
  } = useFetch((signal) => api.listPortfolioMetrics({ signal }), [], { fallback: null });

  const families = manifestData?.families || {};
  const tileMetrics = useMemo(
    () => (manifestData?.metrics || []).filter(m => m.computed_from === 'risk' && m.tile),
    [manifestData]
  );

  const activeIds = useMemo(() => {
    const known = new Set(tileMetrics.map(m => m.id));
    const fromUrl = readList(params, 'risk').filter(id => known.has(id));
    if (fromUrl.length > 0) return fromUrl;
    return tileMetrics.filter(m => m.default_enabled).map(m => m.id);
  }, [params, tileMetrics]);

  const toggle = useCallback((id) => {
    const known = new Set(tileMetrics.map(m => m.id));
    const current = readList(params, 'risk').filter(x => known.has(x));
    const base = current.length > 0
      ? current
      : tileMetrics.filter(m => m.default_enabled).map(m => m.id);
    const next = base.includes(id) ? base.filter(x => x !== id) : [...base, id];
    setParams(p => withParams(p, { risk: next.length ? next.join(',') : null }));
  }, [params, setParams, tileMetrics]);

  const enabled = activeIds.length > 0 && !!request;
  const requestJson = request ? JSON.stringify(request) : '';
  const {
    data: valuesData,
    loading: valuesLoading,
    error: valuesError,
    retry: retryValues,
  } = useFetch(
    (signal) => (enabled ? api.getPortfolioRisk(request, { signal }) : Promise.resolve(null)),
    [enabled, requestJson],
    { fallback: null }
  );

  const retry = useCallback(() => { retryManifest(); retryValues(); }, [retryManifest, retryValues]);

  return {
    tileMetrics,
    families,
    activeIds,
    toggle,
    isActive: (id) => activeIds.includes(id),
    values: valuesData || {},
    reasons: valuesData?.reasons || {},
    loading: manifestLoading || (enabled && valuesLoading),
    error: manifestError || (enabled ? valuesError : null),
    retry,
  };
}
