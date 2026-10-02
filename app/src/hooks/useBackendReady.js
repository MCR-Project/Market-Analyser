/**
 * useBackendReady — has the backend answered yet?
 *
 * On Render's free plan the API sleeps after 15 minutes idle and takes about a
 * minute to wake, while the static frontend loads instantly. Every request the
 * page makes in that minute is a retry loop of its own (useFetch), so without
 * this the app mounts, fires a dozen requests that all hang, and shows a dozen
 * loading skeletons for a minute. This probes `/health` once, before anything
 * else mounts, and lets BackendGate hold the launch screen until it answers.
 *
 * Returns `{ ready, waitedMs }`. `ready` latches: once the backend has
 * answered, a later sleep is the business of the per-request retries, not of
 * putting the launch screen back over a page someone is reading.
 *
 * The probe retries on every failure, whatever it is - a 5xx from Render's
 * proxy, a refused connection, the CORS-less wake-up page that fetch reports
 * as a TypeError. They all mean "not yet" here, and /health is never
 * rate-limited (backend/rate_limit.py), so a fixed short interval costs
 * nothing. Each attempt is capped so a request the proxy holds open for the
 * whole boot is abandoned and re-asked rather than waited on blind.
 *
 * `waitedMs` is ticked by a timer so the gate can move between the phases in
 * utils/launchScreen.js; it is the one timer here, and it stops with `ready`.
 */
import { useEffect, useState } from 'react';
import { api } from '../utils/api';

const ATTEMPT_TIMEOUT_MS = 15_000;
const RETRY_DELAY_MS = 1_500;
const TICK_MS = 250;

export function useBackendReady() {
  const [ready, setReady] = useState(false);
  const [waitedMs, setWaitedMs] = useState(0);

  useEffect(() => {
    if (ready) return undefined;

    const startedAt = Date.now();
    const controller = new AbortController();
    let retryTimer = null;

    const probe = async () => {
      const attempt = new AbortController();
      const onOuterAbort = () => attempt.abort();
      controller.signal.addEventListener('abort', onOuterAbort, { once: true });
      const timeout = setTimeout(() => attempt.abort(), ATTEMPT_TIMEOUT_MS);
      try {
        await api.ping({ signal: attempt.signal });
        if (!controller.signal.aborted) setReady(true);
      } catch {
        if (controller.signal.aborted) return;
        retryTimer = setTimeout(probe, RETRY_DELAY_MS);
      } finally {
        clearTimeout(timeout);
        controller.signal.removeEventListener('abort', onOuterAbort);
      }
    };
    probe();

    const tick = setInterval(() => setWaitedMs(Date.now() - startedAt), TICK_MS);

    return () => {
      controller.abort();
      clearTimeout(retryTimer);
      clearInterval(tick);
    };
  }, [ready]);

  return { ready, waitedMs };
}
