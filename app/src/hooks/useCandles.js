/**
 * useCandles — `[on, setOn]`: whether price charts draw candles, the one
 * switch every chart shares (issue #152). All the rules live in
 * `store/candlePreference.js`; this only hands it the browser's storage and
 * lets React subscribe.
 *
 * The store is made once, at import, over `window.localStorage` - read inside
 * a `try`, because touching it is what throws when site data is blocked. It
 * listens for other tabs' `storage` events for the life of the page: a
 * listener per chart would be one more thing to leak, and the store already
 * ignores every key but its own.
 */
import { useSyncExternalStore } from 'react';
import { createCandlePreference } from '../store/candlePreference';

function browserStorage() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

const preference = createCandlePreference(browserStorage());
window.addEventListener('storage', preference.handleStorageEvent);

export function useCandles() {
  // Off on the server render: nothing here runs there today, but the
  // snapshot React asks for must exist.
  const on = useSyncExternalStore(preference.subscribe, preference.get, () => false);
  return [on, preference.set];
}
