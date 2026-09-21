/**
 * useFreshness — reads how fresh the data is for the shared Header (issue #154).
 *
 * The header outlives the pages under it, and the figure is about the whole
 * database rather than any one fund, so the layout owns this fetch instead of
 * a page publishing it (the way useLiveStatus does for the connectivity
 * badge). It is asked for only once the app reaches a page that reads prices —
 * the Docs page shows no market data, so a data-currency indicator there would
 * be noise, and opening the app on it costs no request.
 *
 * One request per load, on purpose: no timer and no polling. The page is
 * reloaded well inside a day, which is the only rate this figure changes at,
 * so the cost is that a tab left open across a late run keeps showing what it
 * first read until it is reloaded.
 *
 * What is *judged* is a separate matter from what is fetched. The deadline is
 * compared with the browser's clock when the answer arrives and again each time
 * the tab comes back into view (focus, or leaving the background), so a tab
 * left open for days turns to "behind" and its "3h ago" moves on the moment it
 * is looked at, instead of claiming a green "Refreshed 30m ago" it stopped
 * being true of long ago. That is an event, not a timer, and it costs no
 * request; the clock is read in the handler, never during render.
 *
 * Returns `undefined` while there is nothing to show — before the first page
 * that reads prices, and while the first request is in flight — so the header
 * does not flash "unknown" on every load. A request that fails (useFetch has
 * its own retries for a 503) reads as unknown, per utils/freshness.js.
 */
import { useEffect, useMemo, useState } from 'react';
import { api } from '../utils/api';
import { describeFreshness } from '../utils/freshness';
import { useFetch } from './useFetch';

export function useFreshness(onPriceReadingPage) {
  // Adjusted during render rather than in an effect: once the app has been
  // on such a page, it is wanted for good, even after moving on to Docs.
  const [requested, setRequested] = useState(false);
  if (onPriceReadingPage && !requested) setRequested(true);

  const { data, error } = useFetch(
    async (signal) => {
      if (!requested) return null;
      const record = await api.getFreshness({ signal });
      return { record, receivedAt: Date.now() };
    },
    [requested],
  );

  // useFetch clears `error` at the start of each of its own retries, so the
  // failure is remembered here: without it the badge would flicker between
  // "unknown" and nothing for as long as the backend stays unreachable.
  const [failed, setFailed] = useState(false);
  if (error && !failed) setFailed(true);

  // The browser's clock the last time the tab came back into view: what the
  // answer is judged against once it is older than the moment it arrived.
  const [backInViewAt, setBackInViewAt] = useState(0);
  useEffect(() => {
    const judgeAgain = () => {
      if (!document.hidden) setBackInViewAt(Date.now());
    };
    document.addEventListener('visibilitychange', judgeAgain);
    window.addEventListener('focus', judgeAgain);
    return () => {
      document.removeEventListener('visibilitychange', judgeAgain);
      window.removeEventListener('focus', judgeAgain);
    };
  }, []);

  // Memoised so Header's `memo` still means something: a fresh object every
  // render would make its `freshness` prop never compare equal.
  return useMemo(() => {
    if (!requested) return undefined;
    if (data) {
      const now = Math.max(data.receivedAt, backInViewAt);
      return {
        ...describeFreshness(now, data.record),
        finishedAt: data.record?.finishedAt ?? null,
      };
    }
    return failed ? { ...describeFreshness(0, null), finishedAt: null } : undefined;
  }, [requested, data, failed, backInViewAt]);
}
