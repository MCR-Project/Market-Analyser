/**
 * useDeepFill - a fund's Deep-fill status, kept current, and the two presses
 * that change it (issue #172).
 *
 * Returns `{ status, pending, actionError, start, cancel }`. `status` is the
 * backend's own answer (`GET /api/deep-fill/{id}`) or null until it has come;
 * utils/deepFill.js decides what the page makes of it.
 *
 * Not built on `useFetch`: the status is asked again on a schedule the answer
 * itself sets (`nextStatusPoll`: every 2s while a job runs, just after a result
 * should expire, never when nothing is moving), which is not a retry. That makes
 * this one of the fetches `app/CLAUDE.md` says must apply the retry contract by
 * hand, and it does, on the shared schedule (`retrySchedule.js`):
 *
 *  - a failure `isTransientError` calls transient (network, 429, 5xx) is asked
 *    again on the backoff, never sooner than its `Retry-After`, and given up on
 *    after `MAX_AUTO_RETRIES`, keeping the last status it had;
 *  - any other failure (a 4xx) is never asked again, and likewise keeps it;
 *  - except that a job last seen *running* is never given up on: the backend
 *    restarting or a long outage mid-job would otherwise freeze the chip at its
 *    last count for good and the page would never learn the fund had finished.
 *    It keeps asking at the schedule's slowest pace (60s).
 *
 * Presses are not retried at all. Start and cancel are something a person did,
 * and a refusal (403 off on this version, 409 another fund's job holds the slot,
 * 400 this fund cannot be deep-filled) is a stable answer: it is shown, in words
 * (`describeActionError`), and the person decides. A press that succeeds hands
 * the page the status it answered, so the button changes at once rather than a
 * poll later.
 *
 * Every status seen is reported to `store/deepFillEpoch`, which is what makes
 * the page's other requests read the fund again when it becomes deep-filled or
 * stops being.
 *
 * The tab coming back into view asks again: a fund left idle is not polled, and
 * a result may have expired, or a job finished, while nobody was looking.
 */
import { useCallback, useEffect, useState } from 'react';
import { api, isTransientError } from '../utils/api';
import { nextStatusPoll, describeActionError } from '../utils/deepFill';
import { MAX_AUTO_RETRIES, retryDelayMs } from '../utils/retrySchedule';
import { observeDeepFill, forgetDeepFill } from '../store/deepFillEpoch';

export function useDeepFill(etfId) {
  // Keyed by the fund it was asked for, so switching funds never shows the
  // last one's status for a render (adjusted by reading, not by an effect).
  const [snapshot, setSnapshot] = useState({ etfId: null, status: null });
  // What a press is doing, and why one failed, are each about the fund they were
  // pressed on: a press that settles after the user has moved to another fund
  // must not disable that fund's buttons or put its refusal in that fund's dialog.
  const [pressing, setPressing] = useState(null); // { etfId, kind } | null
  const [failure, setFailure] = useState(null);   // { etfId, message } | null
  // Bumped to make the polling effect start over: after a press, and when the
  // tab returns.
  const [round, setRound] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer = null;
    let failures = 0;
    let lastState = null;

    const poll = async () => {
      try {
        const status = await api.getDeepFill(etfId, { signal: controller.signal });
        if (controller.signal.aborted) return;
        failures = 0;
        lastState = status.state;
        observeDeepFill(etfId, status.asOf);
        setSnapshot({ etfId, status });
        const delay = nextStatusPoll(status, Date.now());
        if (delay !== null) timer = setTimeout(poll, delay);
      } catch (err) {
        if (controller.signal.aborted) return;
        console.warn('[useDeepFill] status request failed:', err.message);
        if (isTransientError(err) && (failures < MAX_AUTO_RETRIES || lastState === 'running')) {
          failures += 1;
          timer = setTimeout(poll, retryDelayMs(Math.min(failures, MAX_AUTO_RETRIES), (err.retryAfter ?? 0) * 1000));
        }
      }
    };

    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [etfId, round]);

  // Stop remembering the fund when the page stops watching it, so coming back to
  // it later takes a fresh baseline (store/deepFillEpoch.js, `forgetDeepFill`).
  useEffect(() => () => forgetDeepFill(etfId), [etfId]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') setRound((n) => n + 1);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  const press = useCallback(async (kind, request) => {
    setPressing({ etfId, kind });
    setFailure(null);
    try {
      const status = await request(etfId);
      observeDeepFill(etfId, status.asOf);
      setSnapshot({ etfId, status });
    } catch (err) {
      setFailure({ etfId, message: describeActionError(err) });
    } finally {
      setPressing(null);
      // Whatever happened, the truth is on the server: a 409 means a job this
      // page had not seen, a 403 that the version changed under it.
      setRound((n) => n + 1);
    }
  }, [etfId]);

  const start = useCallback(() => press('start', api.startDeepFill), [press]);
  const cancel = useCallback(() => press('cancel', api.cancelDeepFill), [press]);

  return {
    status: snapshot.etfId === etfId ? snapshot.status : null,
    pending: pressing?.etfId === etfId ? pressing.kind : null,
    actionError: failure?.etfId === etfId ? failure.message : null,
    start,
    cancel,
  };
}
