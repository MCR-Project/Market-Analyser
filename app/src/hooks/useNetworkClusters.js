/**
 * useNetworkClusters — whether the network view outlines its clusters
 * (issue #144), kept in the URL like every other piece of view state here so
 * a reload or a shared link opens the same graph.
 *
 * `?networkClusters=on` turns the outlines on; the parameter is absent when
 * they are off, which is the default, so the plain URL is the plain graph.
 * Its own key, written through `withParams` so nothing else in the query
 * string is dropped; anything other than `on` reads as off (see
 * `readChoice`).
 */
import { useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { readChoice, withParams } from '../utils/searchParams';

export function useNetworkClusters() {
  const [params, setParams] = useSearchParams();

  const showClusters = readChoice(params, 'networkClusters', ['off', 'on'], 'off') === 'on';

  const setShowClusters = useCallback(
    (on) => setParams(p => withParams(p, { networkClusters: on ? 'on' : null })),
    [setParams]
  );

  return { showClusters, setShowClusters };
}
