/**
 * recentStocks — which tickers were opened on the Stock page, most recent
 * first, held once for every sidebar that asks (issue #158). Shaped the
 * same way `candlePreference.js` is: the store holds only tickers, never
 * name/logo/sector — those are derived, changeable facts a sidebar reads
 * fresh through the same batch stock lookup peer cards already use, not a
 * snapshot that could go stale sitting in `localStorage`.
 *
 * `localStorage`, one key, a JSON array capped at MAX_RECENT_STOCKS. Same
 * three rules as candlePreference:
 *
 * - **One list means one store.** Opening a stock from the sidebar itself,
 *   from a link, or by typing a symbol all have to update the same list a
 *   moment later - a copy of it in a component would drift.
 * - **Storage failure never breaks the feature.** Reading
 *   `window.localStorage` is itself what throws when site data is blocked,
 *   so every access is inside a `try`, and a refused write keeps the list
 *   for the session rather than losing the visit.
 * - **A change from another tab arrives without being written back.** That
 *   tab already wrote it; echoing it would only start a loop.
 *
 * The storage is passed in so none of this needs a browser to be tested;
 * `hooks/useRecentStocks.js` is the thin wrapper that hands it the real one.
 */

export const RECENT_STOCKS_KEY = 'market-analyser.recent-stocks';
export const MAX_RECENT_STOCKS = 20;

/**
 * A recently-viewed list over `storage` (anything with
 * `getItem`/`setItem`/`removeItem`, or null when there is none):
 * `{ get, add, subscribe, handleStorageEvent }`.
 */
export function createRecentStocks(storage) {
  let value = null; // ticker[], read lazily, so a store made at import time touches nothing
  const listeners = new Set();

  function read() {
    try {
      const raw = storage?.getItem(RECENT_STOCKS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.every(entry => typeof entry === 'string') ? parsed : [];
    } catch {
      return [];
    }
  }

  function get() {
    if (value === null) value = read();
    return value;
  }

  function change(next) {
    value = next;
    listeners.forEach(listener => listener());
  }

  function write(next) {
    try {
      if (!storage) return false;
      storage.setItem(RECENT_STOCKS_KEY, JSON.stringify(next));
      return true;
    } catch {
      return false;
    }
  }

  /** Record a visit to `ticker`: moves it to the front, deduplicated,
   *  capped at MAX_RECENT_STOCKS with the oldest dropped first. A blank
   *  symbol (nothing resolved yet) changes nothing. Returns the new list -
   *  false from the underlying write, like candlePreference.set, would be
   *  one more thing every caller has to check for no benefit, since a
   *  refused write already keeps the visit for the session either way. */
  function add(ticker) {
    const symbol = (ticker || '').trim().toUpperCase();
    if (!symbol) return get();
    const next = [symbol, ...get().filter(entry => entry !== symbol)].slice(0, MAX_RECENT_STOCKS);
    change(next);
    write(next);
    return next;
  }

  function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  /** Take in a `storage` event from another tab: its own key changing, or
   *  every key going at once (`key` null, site data cleared). */
  function handleStorageEvent({ key, newValue }) {
    if (key !== RECENT_STOCKS_KEY && key !== null) return;
    if (key === null || !newValue) {
      change([]);
      return;
    }
    try {
      const parsed = JSON.parse(newValue);
      change(Array.isArray(parsed) && parsed.every(entry => typeof entry === 'string') ? parsed : []);
    } catch {
      change([]);
    }
  }

  return { get, add, subscribe, handleStorageEvent };
}
