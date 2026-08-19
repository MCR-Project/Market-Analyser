/**
 * useFetch — generic data fetching hook with abort support.
 *
 * Uses a ref for the fetcher to avoid stale closure issues.
 * Clears data immediately when dependencies change.
 * `retry()` re-runs the current fetch (e.g. from an error state's
 * Retry button) without needing a full page reload. `retry(true)` marks
 * that one re-run as a forced refresh (passed as the fetcher's second
 * arg) - fetchers that support bypassing their own cache (e.g. a
 * `refresh` API param) can read it to do so.
 */
import { useState, useEffect, useRef, useCallback } from 'react';

export function useFetch(fetcher, deps = [], { fallback = null } = {}) {
  const [data, setData] = useState(fallback);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const fetcherRef = useRef(fetcher);
  const forceRef = useRef(false);
  const abortRef = useRef(null);

  // Always keep the latest fetcher in the ref — updated in its own effect
  // (runs after every render) rather than during render, since refs aren't
  // meant to be written while rendering.
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const retry = useCallback((force = false) => {
    forceRef.current = force;
    setAttempt(a => a + 1);
  }, []);

  // Clear stale data as soon as the fetch key changes, during render rather
  // than at the top of the effect below — see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  // `deps` is caller-supplied and arbitrary-length, so it's collapsed into
  // one comparable key rather than tracked field-by-field. Every call site
  // passes primitives (ids, joined ticker lists), so JSON.stringify is a
  // stable, order-sensitive key here.
  const key = JSON.stringify([...deps, attempt]);
  const [prevKey, setPrevKey] = useState(key);
  if (key !== prevKey) {
    setPrevKey(key);
    setData(fallback);
    setLoading(true);
    setError(null);
  }

  useEffect(() => {
    // Abort any in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Consume the force flag so only this one run is forced
    const force = forceRef.current;
    forceRef.current = false;

    // Call the latest fetcher from the ref (never stale)
    fetcherRef.current(controller.signal, force)
      .then(result => {
        if (!controller.signal.aborted) {
          setData(result);
          setLoading(false);
        }
      })
      .catch(err => {
        if (!controller.signal.aborted) {
          console.warn('[useFetch] request failed:', err.message);
          setError(err);
          setLoading(false);
        }
      });

    return () => controller.abort();
    // deps is a caller-supplied, arbitrary-length array by design (the
    // whole point of this hook); exhaustive-deps can't verify it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt]);

  return { data, loading, error, retry };
}
