/**
 * useDeepFillEpoch - the fund's Deep-fill epoch (store/deepFillEpoch.js), as a
 * number a data hook adds to its `useFetch` dependencies so the request is made
 * again when the fund becomes deep-filled or stops being. A primitive, as
 * `useFetch`'s `deps` must be.
 */
import { useSyncExternalStore } from 'react';
import { deepFillEpoch, subscribeDeepFill } from '../store/deepFillEpoch';

export function useDeepFillEpoch(etfId) {
  return useSyncExternalStore(subscribeDeepFill, () => deepFillEpoch(etfId));
}
