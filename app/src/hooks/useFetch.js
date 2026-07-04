/**
 * useFetch — generic data fetching hook with abort support.
 *
 * Uses a ref for the fetcher to avoid stale closure issues.
 * Clears data immediately when dependencies change.
 */
import { useState, useEffect, useRef } from 'react';

export function useFetch(fetcher, deps = [], { fallback = null } = {}) {
  const [data, setData] = useState(fallback);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const fetcherRef = useRef(fetcher);
  const abortRef = useRef(null);

  // Always keep the latest fetcher in the ref
  fetcherRef.current = fetcher;

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
          console.warn('[useFetch] falling back to mock data:', err.message);
          setError(err);
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, deps);

  return { data, loading, error };
}
