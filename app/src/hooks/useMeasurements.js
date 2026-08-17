/**
 * useMeasurements — discovers measurement plugins from the backend,
 * manages which are active, and fetches per-ticker data for the table.
 *
 * On mount: fetches the manifest, auto-enables measurements marked default_enabled.
 * On ETF change: refetches every active measurement (their data is tied
 * to the ETF). On toggle: fetches only the newly-activated measurement(s)
 * and clears state for the newly-deactivated one(s) — existing columns
 * are left untouched.
 * Results are stored as:
 *   { [measurementId]: { per_ticker: {NVDA: 7.9, ...}, per_ticker_mdx: {NVDA: "**7.9%**", ...}, ... } }
 * `per_ticker` (raw numbers) drives sorting/filtering; `per_ticker_mdx`
 * (backend-rendered markdown) is what's actually displayed in the table.
 */
import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useFetch } from './useFetch';
import { api } from '../utils/api';

export function useMeasurements(etfId) {
  const [activeIds, setActiveIds] = useState(null); // null = not yet initialized
  const [results, setResults] = useState({});
  const [loading, setLoading] = useState({});
  const abortRefs = useRef({});
  const initializedRef = useRef(false);
  // Tracks what was fetched last time the results effect ran, so it can
  // diff against the new activeIds/etfId and only fetch what's actually
  // new instead of re-running every active measurement on every toggle.
  const prevActiveIdsRef = useRef([]);
  const prevEtfIdRef = useRef(etfId);

  // Fetch the manifest via useFetch so a failed attempt (e.g. the page
  // loaded before the backend was up) can be re-run through retryManifest
  // instead of leaving the measurement list empty until a full reload.
  const { data: manifestData, retry: retryManifest } = useFetch(
    (signal) => api.listMeasurements({ signal }),
    [],
    { fallback: null }
  );
  // Stable reference while manifestData is null — this feeds the results
  // effect's dependency array, so it must not be a fresh [] every render.
  const manifest = useMemo(() => manifestData || [], [manifestData]);

  // Auto-enable defaults once, when the manifest first arrives
  useEffect(() => {
    if (manifestData && !initializedRef.current) {
      const defaults = manifestData.filter(m => m.default_enabled).map(m => m.id);
      setActiveIds(defaults);
      initializedRef.current = true;
    }
  }, [manifestData]);

  const toggle = useCallback((id) => {
    setActiveIds(prev => {
      const list = prev || [];
      return list.includes(id) ? list.filter(x => x !== id) : [...list, id];
    });
  }, []);

  // Fetch results for active measurements when etfId or activeIds change.
  // Diffs against what was active last run: an ETF change invalidates
  // every currently-active measurement (all refetch), but a plain toggle
  // only fetches the newly-added id(s) and clears the newly-removed
  // one(s) — enabling a fourth column shouldn't abort and re-run the
  // three already loaded.
  useEffect(() => {
    const ids = activeIds || [];
    const prevIds = prevActiveIdsRef.current;
    const etfChanged = prevEtfIdRef.current !== etfId;

    const idsToFetch = etfChanged ? ids : ids.filter(id => !prevIds.includes(id));
    const idsToAbort = etfChanged ? prevIds : prevIds.filter(id => !ids.includes(id));
    // Only clear state for ids that are truly gone, not ones being
    // refetched under a new etfId (those get fresh state from the fetch
    // below instead of a delete-then-set race).
    const idsToClear = idsToAbort.filter(id => !idsToFetch.includes(id));

    for (const id of idsToAbort) {
      abortRefs.current[id]?.abort();
      delete abortRefs.current[id];
    }

    for (const id of idsToFetch) {
      const m = manifest.find(x => x.id === id);
      if (!m) continue;

      const ctrl = new AbortController();
      abortRefs.current[id] = ctrl;
      setLoading(prev => ({ ...prev, [id]: true }));

      api.runMeasurement(m.route, { etf_id: etfId }, { signal: ctrl.signal })
        .then(data => {
          if (!ctrl.signal.aborted) {
            setResults(prev => ({ ...prev, [id]: data }));
            setLoading(prev => ({ ...prev, [id]: false }));
          }
        })
        .catch(() => {
          if (!ctrl.signal.aborted) {
            setResults(prev => ({ ...prev, [id]: null }));
            setLoading(prev => ({ ...prev, [id]: false }));
          }
        });
    }

    // Remove results/loading for deactivated measurements — otherwise a
    // toggled-off measurement's stale value (and a stuck `loading: true`)
    // lingers in the map indefinitely.
    if (idsToClear.length) {
      setResults(prev => {
        const next = { ...prev };
        for (const id of idsToClear) delete next[id];
        return next;
      });
      setLoading(prev => {
        const next = { ...prev };
        for (const id of idsToClear) delete next[id];
        return next;
      });
    }

    prevActiveIdsRef.current = ids;
    prevEtfIdRef.current = etfId;
  }, [activeIds, etfId, manifest]);

  // Abort any still in-flight measurement requests on unmount.
  useEffect(() => {
    const refs = abortRefs.current;
    return () => {
      for (const ctrl of Object.values(refs)) ctrl.abort();
    };
  }, []);

  // Build a lookup: ticker → { measurementId: rawValue }
  // Raw values are only used for client-side sorting/filtering.
  const getTickerValues = useCallback((ticker) => {
    const vals = {};
    for (const id of (activeIds || [])) {
      const data = results[id];
      if (data?.per_ticker) {
        vals[id] = data.per_ticker[ticker] ?? null;
      }
    }
    return vals;
  }, [activeIds, results]);

  // Build a lookup: ticker → { measurementId: markdownSnippet }
  // This is what's actually displayed — the backend has already rendered
  // each value (bold/percent/bar/etc.), so the table just displays the
  // markdown as-is instead of branching on a per-measurement `format`.
  const getTickerMdx = useCallback((ticker) => {
    const mdx = {};
    for (const id of (activeIds || [])) {
      const data = results[id];
      if (data?.per_ticker_mdx) {
        mdx[id] = data.per_ticker_mdx[ticker] ?? null;
      }
    }
    return mdx;
  }, [activeIds, results]);

  // Get active measurement manifests in order
  const activeManifests = (activeIds || [])
    .map(id => manifest.find(m => m.id === id))
    .filter(Boolean);

  return {
    manifest,
    retryManifest,
    activeIds: activeIds || [],
    activeManifests,
    toggle,
    results,
    loading,
    getTickerValues,
    getTickerMdx,
    isActive: (id) => (activeIds || []).includes(id),
  };
}
