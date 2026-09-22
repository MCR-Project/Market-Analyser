/**
 * useRecentStocks — `[tickers, visit]`: the Stock page's recently-viewed
 * list, most recent first (issue #158). All the rules live in
 * `store/recentStocks.js`; this only hands it the browser's storage and
 * lets React subscribe, the same shape `useCandles` already follows.
 */
import { useSyncExternalStore } from 'react';
import { createRecentStocks } from '../store/recentStocks';

function browserStorage() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

const store = createRecentStocks(browserStorage());
window.addEventListener('storage', store.handleStorageEvent);

export function useRecentStocks() {
  // Empty on the server render: nothing here runs there today, but the
  // snapshot React asks for must exist.
  const tickers = useSyncExternalStore(store.subscribe, store.get, () => []);
  return [tickers, store.add];
}
