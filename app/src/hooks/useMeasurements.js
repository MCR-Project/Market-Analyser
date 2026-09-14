/**
 * useMeasurements — discovers measurement columns from the backend,
 * manages which are active, and fetches per-ticker data for the table.
 *
 * The manifest (`GET /api/measurements`) has one entry per *column*, not
 * per plugin (issue #100): a plugin providing several columns from one
 * computation (upside/downside capture, say) appears as that many
 * independently toggleable rows, each naming `measurement_id` — the
 * plugin that actually computes it — so the toggle state and the table
 * below never have to think about plugins at all, only columns.
 *
 * Fetching still happens once per *plugin*, not per column: enabling a
 * second column of an already-active plugin adds no new request, since
 * `activeMeasurementIds` (below) is the unique set of plugins behind
 * whichever columns are on, and the fetch effect diffs against that set,
 * not against the column list directly.
 *
 * On mount: fetches the manifest, auto-enables columns marked
 * default_enabled. On ETF change: refetches every plugin behind an
 * active column (their data is tied to the ETF). On toggle: fetches only
 * the newly-needed plugin(s) and clears state for the newly-unneeded
 * one(s) — existing columns are left untouched. On a `window` change
 * (issue #101, see useMeasurementWindow): refetches only the plugins
 * behind an *active* window-aware column — a plugin with no window at
 * all (every official one, today) is not touched, and neither is a
 * window-aware plugin none of whose columns happen to be on.
 *
 * `results` is keyed by `measurement_id` (the plugin), not by column,
 * and holds that plugin's whole response — flat
 * (`{ per_ticker: {NVDA: 7.9, ...}, per_ticker_mdx: {...} }`) for a
 * single-column plugin, or nested one level deeper by column key for a
 * multi-column one. `getTickerValues`/`getTickerMdx`/`getTickerReason`
 * are what read either shape back out per column, using
 * `columnsByMeasurement` to know which shape a given plugin's response
 * is in — the one piece of logic that has to know about both shapes, so
 * nothing else in the frontend does. `loading`, by contrast, *is* keyed
 * by column id (expanded from the one plugin-level fetch to every
 * column it serves), because that is what the table reads per column it
 * renders.
 */
import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useFetch } from './useFetch';
import { api, isTransientError } from '../utils/api';
import { MAX_AUTO_RETRIES, retryDelayMs } from '../utils/retrySchedule';

export function useMeasurements(etfId, window) {
  const [activeIds, setActiveIds] = useState(null); // null = not yet initialized; column ids
  const [results, setResults] = useState({}); // keyed by measurement_id (plugin)
  const [loading, setLoading] = useState({}); // keyed by column id
  const abortRefs = useRef({}); // keyed by measurement_id
  const retryTimersRef = useRef({}); // keyed by measurement_id
  // Consecutive auto-retries per plugin (issue #92) - reset by
  // clearRetry below, which already runs both when a plugin is
  // deactivated and right before each fresh run(), so a re-enabled
  // plugin always starts with a full budget.
  const retryCountsRef = useRef({});
  const initializedRef = useRef(false);
  // Tracks what was fetched last time the results effect ran, so it can
  // diff against the new active plugin set and only fetch what's
  // actually new instead of re-running every active plugin on every
  // toggle.
  const prevActiveMeasurementIdsRef = useRef([]);
  const prevEtfIdRef = useRef(etfId);
  const prevWindowRef = useRef(window);

  // Fetch the manifest via useFetch so a failed attempt (e.g. the page
  // loaded before the backend was up) can be re-run through retryManifest
  // instead of leaving the column list empty until a full reload.
  const { data: manifestData, retry: retryManifest } = useFetch(
    (signal) => api.listMeasurements({ signal }),
    [],
    { fallback: null }
  );
  // Stable reference while manifestData is null — this feeds the results
  // effect's dependency array, so it must not be a fresh [] every render.
  const manifest = useMemo(() => manifestData || [], [manifestData]);

  // Every column, grouped by the plugin that provides it. The only place
  // that needs to know a plugin's column count - one to read its
  // response as flat, more than one to read it keyed by column key.
  const columnsByMeasurement = useMemo(() => {
    const map = {};
    for (const column of manifest) {
      (map[column.measurement_id] ??= []).push(column);
    }
    return map;
  }, [manifest]);

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

  // The unique plugins behind whichever columns are active right now -
  // what actually has to be fetched. Toggling on a second column of a
  // plugin already represented here changes nothing about this set,
  // which is what makes that toggle issue no new request.
  const activeMeasurementIds = useMemo(() => {
    const ids = new Set();
    for (const columnId of (activeIds || [])) {
      const column = manifest.find(m => m.id === columnId);
      if (column) ids.add(column.measurement_id);
    }
    return [...ids];
  }, [activeIds, manifest]);

  // Fetch results for active plugins when etfId, the active plugin set,
  // or the shared window changes. Diffs against what was active last
  // run: an ETF change invalidates every currently-active plugin (all
  // refetch), but a plain toggle only fetches the newly-needed plugin(s)
  // and clears the newly-unneeded one(s) — enabling a fourth column
  // shouldn't abort and re-run the three already loaded. A window change
  // (issue #101) is a third, narrower case: it refetches only the
  // plugins whose *active* columns actually declare a window
  // (isWindowAware below) — the acceptance criterion is that changing
  // the control must not so much as touch a non-window-aware column.
  useEffect(() => {
    const ids = activeMeasurementIds;
    const prevIds = prevActiveMeasurementIdsRef.current;
    const etfChanged = prevEtfIdRef.current !== etfId;
    const windowChanged = prevWindowRef.current !== window;

    const columnIdsFor = (measurementId) =>
      (columnsByMeasurement[measurementId] || []).map(c => c.id);

    const isWindowAware = (measurementId) =>
      (columnsByMeasurement[measurementId] || []).some(c => (c.window_options || []).length > 0);

    const idsToFetch = etfChanged
      ? ids
      : ids.filter(id => !prevIds.includes(id) || (windowChanged && isWindowAware(id)));
    const idsToAbort = etfChanged ? prevIds : prevIds.filter(id => !ids.includes(id));
    // Only clear state for ids that are truly gone, not ones being
    // refetched under a new etfId (those get fresh state from the fetch
    // below instead of a delete-then-set race).
    const idsToClear = idsToAbort.filter(id => !idsToFetch.includes(id));

    const setLoadingFor = (measurementId, value) => {
      const columnIds = columnIdsFor(measurementId);
      setLoading(prev => {
        const next = { ...prev };
        for (const columnId of columnIds) next[columnId] = value;
        return next;
      });
    };

    const clearRetry = (id) => {
      if (retryTimersRef.current[id] !== undefined) {
        clearTimeout(retryTimersRef.current[id]);
        delete retryTimersRef.current[id];
      }
      delete retryCountsRef.current[id];
    };

    // Results are fetched here rather than through useFetch (one request
    // per active plugin, keyed off a diff), so they don't inherit its
    // auto-retry and used to stay permanently blank after a cold start
    // even once the backend recovered. Same rule as useFetch, on the same
    // shared schedule (retrySchedule.js, issue #92): re-ask on a transient
    // failure with a backoff that never re-asks a rate limit every 3s
    // forever, give up on a stable one, and stop auto-retrying after
    // MAX_AUTO_RETRIES so a plugin that never comes back reads as failed
    // rather than loading forever. The controller is reused across
    // retries so a toggle-off or ETF change still cancels the whole
    // chain, and `loading` deliberately stays true while retrying - it is
    // still loading.
    const run = (id, m, ctrl) => {
      const params = { etf_id: etfId };
      // Sent only for a plugin that actually declared window_options
      // (issue #101) - a non-window-aware plugin's route generates no
      // such query parameter at all, so sending one would be inert at
      // best; omitting it is what keeps that plugin's request identical
      // to what it always was.
      if ((m.window_options || []).length > 0) params.window = window;
      setLoadingFor(id, true);
      api.runMeasurement(m.route, params, { signal: ctrl.signal })
        .then(data => {
          if (ctrl.signal.aborted) return;
          delete retryCountsRef.current[id];
          setResults(prev => ({ ...prev, [id]: data }));
          setLoadingFor(id, false);
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
          setLoadingFor(id, false);
        });
    };

    for (const id of idsToAbort) {
      abortRefs.current[id]?.abort();
      delete abortRefs.current[id];
      clearRetry(id);
    }

    for (const id of idsToFetch) {
      const m = (columnsByMeasurement[id] || [])[0];
      if (!m) continue;

      // A window change can refetch a plugin that is *not* leaving the
      // active set (so it was never in idsToAbort above) - abort its
      // still-in-flight request for the old window first, or a slow old
      // response landing after the new one would silently overwrite it.
      abortRefs.current[id]?.abort();
      clearRetry(id);
      const ctrl = new AbortController();
      abortRefs.current[id] = ctrl;
      run(id, m, ctrl);
    }

    // Remove results/loading for deactivated plugins — otherwise a
    // toggled-off plugin's stale value (and a stuck `loading: true`)
    // lingers in the map indefinitely.
    if (idsToClear.length) {
      setResults(prev => {
        const next = { ...prev };
        for (const id of idsToClear) delete next[id];
        return next;
      });
      setLoading(prev => {
        const next = { ...prev };
        for (const id of idsToClear) {
          for (const columnId of columnIdsFor(id)) delete next[columnId];
        }
        return next;
      });
    }

    prevActiveMeasurementIdsRef.current = ids;
    prevEtfIdRef.current = etfId;
    prevWindowRef.current = window;
    // columnsByMeasurement is derived from manifest on every render but
    // only actually changes when manifest does, so it is intentionally
    // left out here - including it would refetch on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMeasurementIds, etfId, window]);

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

  // A column's raw value out of its plugin's response, whichever shape
  // that plugin's response is in.
  const columnValue = useCallback((column, field, ticker) => {
    const data = results[column.measurement_id];
    const raw = data?.[field];
    if (!raw) return undefined;
    const multiColumn = (columnsByMeasurement[column.measurement_id] || []).length > 1;
    const perTicker = multiColumn ? raw[column.column_key] : raw;
    return perTicker ? perTicker[ticker] : undefined;
  }, [results, columnsByMeasurement]);

  // Build a lookup: ticker → { columnId: rawValue }
  // Raw values are only used for client-side sorting/filtering.
  const getTickerValues = useCallback((ticker) => {
    const vals = {};
    for (const id of (activeIds || [])) {
      const column = manifest.find(m => m.id === id);
      if (!column) continue;
      const value = columnValue(column, 'per_ticker', ticker);
      if (value !== undefined) vals[id] = value ?? null;
    }
    return vals;
  }, [activeIds, manifest, columnValue]);

  // Build a lookup: ticker → { columnId: markdownSnippet }
  // This is what's actually displayed — the backend has already rendered
  // each value (bold/percent/bar/etc.), so the table just displays the
  // markdown as-is instead of branching on a per-column `format`.
  const getTickerMdx = useCallback((ticker) => {
    const mdx = {};
    for (const id of (activeIds || [])) {
      const column = manifest.find(m => m.id === id);
      if (!column) continue;
      const value = columnValue(column, 'per_ticker_mdx', ticker);
      if (value !== undefined) mdx[id] = value ?? null;
    }
    return mdx;
  }, [activeIds, manifest, columnValue]);

  // Build a lookup: ticker → { columnId: reason string | undefined }
  // (issue #99). Absent for a plugin that never sends per_ticker_reason
  // at all (for this column), or for a ticker it didn't name — MdxCell
  // treats "no reason" and "an empty one" the same way, a plain dash.
  const getTickerReason = useCallback((ticker) => {
    const reasons = {};
    for (const id of (activeIds || [])) {
      const column = manifest.find(m => m.id === id);
      if (!column) continue;
      const reason = columnValue(column, 'per_ticker_reason', ticker);
      if (reason !== undefined) reasons[id] = reason;
    }
    return reasons;
  }, [activeIds, manifest, columnValue]);

  // Get active column manifests in order
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
    getTickerReason,
    isActive: (id) => (activeIds || []).includes(id),
  };
}
