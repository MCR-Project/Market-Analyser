/**
 * useFetch — generic data fetching hook with abort support.
 *
 * Uses a ref for the fetcher to avoid stale closure issues.
 * Clears data immediately when dependencies change.
 * `retry()` re-runs the current fetch (e.g. from an error state's
 * Retry button) without needing a full page reload. `retry(true)` marks
 * that one re-run as a forced refresh (passed as the fetcher's second
 * arg) - fetchers that support bypassing their own cache (e.g. a
 * `refresh` API param) can read it to do so. A manual retry() always
 * resets the auto-retry budget below, since a deliberate click should
 * always get a fresh attempt regardless of how many automatic ones
 * already ran.
 *
 * A transient failure auto-retries instead of sitting broken until a
 * human clicks Retry, on a shared backoff schedule (retrySchedule.js,
 * issue #92): starting at 3s and doubling up to a 60s cap, never
 * shorter than the failed response's own Retry-After. This is what a
 * "cold start" load looks like: the frontend's static assets are served
 * instantly while the backend is still coming up, so the first requests
 * lose that race and every hook built on this one would otherwise fail
 * permanently - the only workaround being a full page reload. The same
 * schedule also covers a slower failure the flat "every 3s" rule this
 * replaced got wrong: Yahoo rate-limiting the backend's shared cloud
 * IP, which can take a full minute to clear and where retrying every 3s
 * the whole time is exactly the traffic that keeps the block in place.
 * After MAX_AUTO_RETRIES consecutive failures it stops on its own -
 * `error.retriesExhausted` is set on that last error so
 * describeFetchError (utils/errorCopy.js) can stop claiming to be
 * retrying and point at the Retry button instead.
 *
 * "Transient" is decided by isTransientError (see utils/api.js): a
 * network-level TypeError, or a 5xx/429 from a server that is up but
 * whose own data source isn't. A cold start produces both, which is why
 * retrying only the network case wasn't enough - the backend binds its
 * port well before Yahoo/Supabase will answer it, so the requests that
 * lose the race come back as 503s, not as connection failures. A 404 or a
 * 400 still does NOT retry: that's a stable answer that would come back
 * identical however many times we asked.
 *
 * Contract on `deps`: every element must be a primitive (string, number,
 * or boolean) - e.g. an id, or a `list.join(',')` for a multi-value key.
 * `deps` is used two different ways that must never disagree: it's
 * collapsed into a JSON string to decide (during render) whether to reset
 * to a loading state, and spread into the effect's own dependency array,
 * which React compares element-by-element with Object.is. Those two
 * comparisons only agree for primitives - an object or function dep can
 * change identity (and therefore the effect's own decision to re-fetch)
 * without its JSON.stringify output changing, silently desyncing the
 * reset from the actual re-fetch. A dev-only console.warn below catches
 * this; there's no way to enforce it at the type level here since deps
 * is a plain array of caller-chosen values.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { isTransientError } from '../utils/api';
import { MAX_AUTO_RETRIES, retryDelayMs } from '../utils/retrySchedule';

export function useFetch(fetcher, deps = [], { fallback = null } = {}) {
  const [data, setData] = useState(fallback);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const fetcherRef = useRef(fetcher);
  const attemptRef = useRef(0);
  const forcedAttemptRef = useRef(-1);
  const abortRef = useRef(null);
  const autoRetryTimeoutRef = useRef(null);
  const warnedNonPrimitiveDepsRef = useRef(false);
  // How many consecutive *automatic* retries have run for the current
  // deps without a success or a manual retry() in between - reset on
  // both (see bumpAttempt/retry below and the deps-change check in the
  // effect), and checked against MAX_AUTO_RETRIES before scheduling
  // another. Deliberately not derived from `attempt`, which also counts
  // manual retries and must not reset this budget when it advances.
  const autoRetryCountRef = useRef(0);
  const lastDepsKeyRef = useRef();

  // Dev-only guard for the contract documented above - a non-primitive dep
  // can make the render-time reset key and the effect's own re-fetch
  // decision disagree. Runs in an effect (not during render, where refs
  // can't be touched) and latches after the first warning so it doesn't
  // spam on every render.
  useEffect(() => {
    if (!import.meta.env?.DEV || warnedNonPrimitiveDepsRef.current) return;
    const badDep = deps.find(d => d !== null && (typeof d === 'object' || typeof d === 'function'));
    if (badDep !== undefined) {
      warnedNonPrimitiveDepsRef.current = true;
      console.warn(
        '[useFetch] deps must be primitives (string/number/boolean) - got',
        badDep,
        '- a non-primitive dep can desync the render-time stale-data reset ' +
        'from the effect\'s own re-fetch decision. Pass a derived primitive ' +
        'instead, e.g. `list.join(\',\')`.'
      );
    }
  });

  // Always keep the latest fetcher in the ref — updated in its own effect
  // (runs after every render) rather than during render, since refs aren't
  // meant to be written while rendering.
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  // `force` is recorded against the attempt number it belongs to rather
  // than as a flag the effect consumes: StrictMode invokes the effect
  // twice for one attempt, and a consumed flag left the second invoke -
  // the one whose request the UI actually shows - unforced, so the manual
  // refresh silently failed to bypass the cache it exists to bypass.
  const bumpAttempt = useCallback((force = false) => {
    const next = attemptRef.current + 1;
    attemptRef.current = next;
    if (force) forcedAttemptRef.current = next;
    setAttempt(next);
  }, []);

  // The function callers get back (an error panel's Retry button, or a
  // hook's own forceRefresh). Distinct from the internal auto-retry path
  // below, which calls bumpAttempt() directly: a human asking again is a
  // deliberate fresh start and always re-arms the auto-retry budget, but
  // the auto-retry timer firing must not reset the very budget it is
  // spending.
  const retry = useCallback((force = false) => {
    autoRetryCountRef.current = 0;
    bumpAttempt(force);
  }, [bumpAttempt]);

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
    // A genuinely new resource (deps changed, independent of attempt)
    // gets a fresh auto-retry budget - otherwise a fetch that exhausted
    // its retries would leave the next one (e.g. after switching ETF)
    // unable to auto-retry at all. Does not fire on a plain attempt bump
    // with the same deps, auto or manual, which is exactly why this is
    // its own check rather than living in the render-time reset above.
    const depsKey = JSON.stringify(deps);
    if (depsKey !== lastDepsKeyRef.current) {
      lastDepsKeyRef.current = depsKey;
      autoRetryCountRef.current = 0;
    }

    // Abort any in-flight request, and any pending auto-retry from a
    // previous failed run - this run supersedes both.
    abortRef.current?.abort();
    if (autoRetryTimeoutRef.current !== null) {
      clearTimeout(autoRetryTimeoutRef.current);
      autoRetryTimeoutRef.current = null;
    }
    const controller = new AbortController();
    abortRef.current = controller;

    // Only the attempt that asked for it is forced - see retry() above.
    const force = forcedAttemptRef.current === attempt;

    // Call the latest fetcher from the ref (never stale)
    fetcherRef.current(controller.signal, force)
      .then(result => {
        if (!controller.signal.aborted) {
          autoRetryCountRef.current = 0;
          setData(result);
          setLoading(false);
        }
      })
      .catch(err => {
        if (!controller.signal.aborted) {
          console.warn('[useFetch] request failed:', err.message);
          // See the file-level doc comment: a transient failure is one
          // that self-heals as the backend and its data sources warm up,
          // so it's worth re-asking. Anything else would just fail the
          // same way again. Capped at MAX_AUTO_RETRIES - past that, mark
          // this failure as the last one it'll try on its own (see
          // describeFetchError, utils/errorCopy.js) and leave it for a
          // manual Retry, which resets the budget above.
          if (isTransientError(err) && autoRetryCountRef.current < MAX_AUTO_RETRIES) {
            autoRetryCountRef.current += 1;
            const delayMs = retryDelayMs(autoRetryCountRef.current, (err.retryAfter ?? 0) * 1000);
            autoRetryTimeoutRef.current = setTimeout(() => bumpAttempt(), delayMs);
          } else if (isTransientError(err)) {
            err.retriesExhausted = true;
          }
          setError(err);
          setLoading(false);
        }
      });

    return () => {
      controller.abort();
      if (autoRetryTimeoutRef.current !== null) {
        clearTimeout(autoRetryTimeoutRef.current);
        autoRetryTimeoutRef.current = null;
      }
    };
    // deps is a caller-supplied, arbitrary-length array by design (the
    // whole point of this hook); exhaustive-deps can't verify it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt]);

  return { data, loading, error, retry };
}
