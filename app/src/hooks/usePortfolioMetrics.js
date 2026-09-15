/**
 * usePortfolioMetrics — the portfolio metric registry, and which tiles
 * are active, held in the URL (issue #104).
 *
 * Mirrors useMeasurements' relationship to the URL, much simplified: a
 * portfolio metric's *value* always comes from the same
 * POST /api/portfolio/simulate response PortfolioPanel already fetches
 * (see portfolio_metrics/base.py's RunMetric) — this hook fetches the
 * *manifest* only, once, and decides which of its tile-eligible entries
 * are switched on.
 *
 * `?metrics=` is a comma-separated id list, read/written through
 * searchParams.js's readList/withParams the same way every other
 * multi-value URL param in this app is — never by replacing the whole
 * query string. Absent, empty, or naming only unknown/non-tile ids falls
 * back to the manifest's own default_enabled set (today's five portfolio-
 * family tiles plus the four account-family ones, which
 * PortfolioSummary.jsx then only actually shows once the run is funded) —
 * the same "canonicalise rather than error" rule every other URL-held
 * selection here follows: a bad link should open the app, not a
 * complaint about itself.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { useFetch } from './useFetch';
import { api } from '../utils/api';
import { readList, withParams } from '../utils/searchParams';

export function usePortfolioMetrics() {
  const [params, setParams] = useSearchParams();

  const { data, loading, error, retry } = useFetch(
    (signal) => api.listPortfolioMetrics({ signal }),
    [],
    { fallback: null }
  );

  // Stable references while data is null, and on every render once it
  // isn't - `data?.metrics || []` would otherwise be a fresh array every
  // render, defeating the useMemo below it feeds.
  const metrics = useMemo(() => data?.metrics || [], [data]);
  const families = data?.families || {};
  // dividendIncome/dividendYield/incomeUnknownFor (tile: false) are never
  // toggleable — the dividend note stays prose (issue #68) — so they are
  // filtered out here, once, rather than by every caller that wants the
  // tile set.
  const tileMetrics = useMemo(() => metrics.filter(m => m.tile), [metrics]);

  const activeIds = useMemo(() => {
    const known = new Set(tileMetrics.map(m => m.id));
    const fromUrl = readList(params, 'metrics').filter(id => known.has(id));
    if (fromUrl.length > 0) return fromUrl;
    return tileMetrics.filter(m => m.default_enabled).map(m => m.id);
  }, [params, tileMetrics]);

  const toggle = useCallback((id) => {
    const known = new Set(tileMetrics.map(m => m.id));
    const current = readList(params, 'metrics').filter(x => known.has(x));
    const base = current.length > 0
      ? current
      : tileMetrics.filter(m => m.default_enabled).map(m => m.id);
    const next = base.includes(id) ? base.filter(x => x !== id) : [...base, id];
    setParams(p => withParams(p, { metrics: next.length ? next.join(',') : null }));
  }, [params, setParams, tileMetrics]);

  return {
    metrics,
    tileMetrics,
    families,
    activeIds,
    toggle,
    isActive: (id) => activeIds.includes(id),
    loading,
    error,
    retry,
  };
}
