/**
 * useFullViewThreshold — the Full view network's Link Threshold (issue #173), kept
 * in the URL like every other piece of view state here so a reload or a shared link
 * opens the same graph.
 *
 * `?threshold=0.55`, omitted at its default (0.5) so the plain URL is the plain
 * view; anything that is not a plain number reads as the default and a number past
 * the slider's ends is held to the nearest end (see `readNumber`). Written through
 * `withParams` so nothing else in the query string is dropped, and with `replace`:
 * a slider drag is dozens of changes and none of them is a place to go Back to.
 *
 * Its own key — not `?window=` or `?matrixOrder=` — and not shared with the normal
 * network, whose edge slider is plain state. They happen to start at the same value
 * (0.5) but are different drawings over different holdings (~46 and ~500) with their
 * own slider ranges, and a link copied from one must not move the other.
 */
import { useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { readNumber, withParams } from '../utils/searchParams';
import { DEFAULT_THRESHOLD, THRESHOLD_MIN, THRESHOLD_MAX } from '../utils/fullNetwork';

export function useFullViewThreshold() {
  const [params, setParams] = useSearchParams();

  const threshold = readNumber(params, 'threshold', DEFAULT_THRESHOLD, THRESHOLD_MIN, THRESHOLD_MAX);

  const setThreshold = useCallback(
    (value) => setParams(
      (p) => withParams(p, { threshold: Math.abs(value - DEFAULT_THRESHOLD) < 1e-9 ? null : value.toFixed(2) }),
      { replace: true }
    ),
    [setParams]
  );

  return { threshold, setThreshold };
}
