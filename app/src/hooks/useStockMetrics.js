/**
 * useStockMetrics — the portfolio metric registry manifest, and which
 * tiles are active on the Stock page (issue #159), held in `?stockMetrics=`.
 *
 * A third, independent consumer of the same `/api/portfolio-metrics`
 * manifest `usePortfolioMetrics` (the portfolio page) and `useFundMetrics`
 * (the fund metrics card) already read — same registry, same
 * `computed_from === 'run'` tile filter `usePortfolioMetrics` uses (a
 * stock's own Run is scored exactly like a portfolio's, so the same
 * exclusions apply: no `computed_from === 'etf_id'` or `'risk'` entry has
 * a value in a Run's response, and dividendIncome/dividendYield/
 * incomeUnknownFor declare `tile: false` and are never toggleable here
 * either), but with its own URL key so it can never collide with
 * `?metrics=` on `/portfolio/...`. Mirrors `usePortfolioMetrics.js`
 * structurally rather than generalising it to take a param name — the
 * same choice already made between that hook and `useFundMetrics.js`, so
 * a change to one registry consumer's own filtering never risks the
 * others.
 *
 * Unlike `usePortfolioMetrics`, this hook does not also hold the values —
 * those come from whichever Run `usePortfolioSimulation` already fetched
 * for the page's basket-of-one portfolio, the same way `PortfolioSummary`
 * reads a portfolio's own `metrics` rather than fetching them separately.
 *
 * Filtered one step further than `usePortfolioMetrics`, to `family ===
 * 'portfolio'` only: the Run a Stock page scores is always a single lump
 * sum with no schedule (issue #159's own $100, no contribution or
 * withdrawal, ever), so every `family === 'account'` entry
 * (contributed/withdrawn/totalInvested/gain/moneyWeightedReturn) would be
 * either permanently zero, a trivial constant, or - moneyWeightedReturn,
 * the IRR of a run with exactly one inflow and one outflow - a literal
 * duplicate of `cagr` under a different name. `PortfolioSummary.jsx` only
 * shows that family once a run is actually funded beyond its opening
 * lump sum; a Stock page Run never is, so the equivalent here is to never
 * offer those tiles at all rather than show a picker full of dead rows.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { useFetch } from './useFetch';
import { api } from '../utils/api';
import { readList, withParams } from '../utils/searchParams';

export function useStockMetrics() {
  const [params, setParams] = useSearchParams();

  const { data, loading, error, retry } = useFetch(
    (signal) => api.listPortfolioMetrics({ signal }),
    [],
    { fallback: null }
  );

  const metrics = useMemo(() => data?.metrics || [], [data]);
  const families = data?.families || {};
  const tileMetrics = useMemo(
    () => metrics.filter(m => m.tile && m.computed_from === 'run' && m.family === 'portfolio'),
    [metrics]
  );

  const activeIds = useMemo(() => {
    const known = new Set(tileMetrics.map(m => m.id));
    const fromUrl = readList(params, 'stockMetrics').filter(id => known.has(id));
    if (fromUrl.length > 0) return fromUrl;
    return tileMetrics.filter(m => m.default_enabled).map(m => m.id);
  }, [params, tileMetrics]);

  const toggle = useCallback((id) => {
    const known = new Set(tileMetrics.map(m => m.id));
    const current = readList(params, 'stockMetrics').filter(x => known.has(x));
    const base = current.length > 0
      ? current
      : tileMetrics.filter(m => m.default_enabled).map(m => m.id);
    const next = base.includes(id) ? base.filter(x => x !== id) : [...base, id];
    setParams(p => withParams(p, { stockMetrics: next.length ? next.join(',') : null }));
  }, [params, setParams, tileMetrics]);

  return {
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
