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
import { api, isTransientError } from '../utils/api';
import { MAX_AUTO_RETRIES, retryDelayMs } from '../utils/retrySchedule';

export function useMeasurements(etfId) {
  const [activeIds, setActiveIds] = useState(null); // null = not yet initialized
  const [results, setResults] = useState({});
  const [loading, setLoading] = useState({});
  const abortRefs = useRef({});
  const retryTimersRef = useRef({});
  // Consecutive auto-retries per measurement id (issue #92) - reset by
  // clearRetry below, which already runs both when a measurement is
  // deactivated and right before each fresh run(), so a re-enabled
  // measurement always starts with a full budget.
  const retryCountsRef = useRef({});
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

    const clearRetry = (id) => {
      if (retryTimersRef.current[id] !== undefined) {
        clearTimeout(retryTimersRef.current[id]);
        delete retryTimersRef.current[id];
      }
      delete retryCountsRef.current[id];
    };

    // Results are fetched here rather than through useFetch (one request
    // per active measurement, keyed off a diff), so they don't inherit its
    // auto-retry and used to stay permanently blank after a cold start
    // even once the backend recovered. Same rule as useFetch, on the same
    // shared schedule (retrySchedule.js, issue #92): re-ask on a transient
    // failure with a backoff that never re-asks a rate limit every 3s
    // forever, give up on a stable one, and stop auto-retrying after
    // MAX_AUTO_RETRIES so a column that never comes back reads as failed
    // rather than loading forever. The controller is reused across
    // retries so a toggle-off or ETF change still cancels the whole
    // chain, and `loading` deliberately stays true while retrying - it is
    // still loading.
    const run = (id, m, ctrl) => {
      setLoading(prev => ({ ...prev, [id]: true }));
      api.runMeasurement(m.route, { etf_id: etfId }, { signal: ctrl.signal })
        .then(data => {
          if (ctrl.signal.aborted) return;
          delete retryCountsRef.current[id];
          setResults(prev => ({ ...prev, [id]: data }));
          setLoading(prev => ({ ...prev, [id]: false }));
        })
        .catch(err => {
          if (ctrl.signal.aborted) return;
          if (isTransientError(err)) {
            const count = (retryCountsRef.current[id] ?? 0) + 1;
            if (count <= MAX_AUTO_RETRIES) {
              retryCountsRef.current[id] = count;
              const delayMs = retryDelayMs(count, (err.retryAfter ?? 0) * 1000);
              retryTimersRef.current[id] = setTimeout(() => {
                delete retryTimersRef.current[id];
                if (!ctrl.signal.aborted) run(id, m, ctrl);
              }, delayMs);
              return;
            }
            delete retryCountsRef.current[id];
          }
          setResults(prev => ({ ...prev, [id]: null }));
          setLoading(prev => ({ ...prev, [id]: false }));
        });
    };

    for (const id of idsToAbort) {
      abortRefs.current[id]?.abort();
      delete abortRefs.current[id];
      clearRetry(id);
    }

    for (const id of idsToFetch) {
      const m = manifest.find(x => x.id === id);
      if (!m) continue;

      clearRetry(id);
      const ctrl = new AbortController();
      abortRefs.current[id] = ctrl;
      run(id, m, ctrl);
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

  // Abort any still in-flight measurement requests on unmount, and drop
  // any retry that hasn't fired yet.
  useEffect(() => {
    const refs = abortRefs.current;
    const timers = retryTimersRef.current;
    return () => {
      for (const ctrl of Object.values(refs)) ctrl.abort();
      for (const timer of Object.values(timers)) clearTimeout(timer);
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
