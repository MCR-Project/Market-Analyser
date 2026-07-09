/**
 * useFetch — generic data fetching hook with abort support.
 *
 * Uses a ref for the fetcher to avoid stale closure issues.
 * Clears data immediately when dependencies change.
 * `retry()` re-runs the current fetch (e.g. from an error state's
 * Retry button) without needing a full page reload.
 */
import { useState, useEffect, useRef, useCallback } from 'react';

export function useFetch(fetcher, deps = [], { fallback = null } = {}) {
  const [data, setData] = useState(fallback);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const fetcherRef = useRef(fetcher);
  const abortRef = useRef(null);

  // Always keep the latest fetcher in the ref
  fetcherRef.current = fetcher;

  const retry = useCallback(() => setAttempt(a => a + 1), []);

  useEffect(() => {
    // Abort any in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Clear stale data immediately
    setData(fallback);
    setLoading(true);
    setError(null);

    // Call the latest fetcher from the ref (never stale)
    fetcherRef.current(controller.signal)
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
  }, [...deps, attempt]);

  return { data, loading, error, retry };
}
