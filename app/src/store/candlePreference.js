/**
 * candlePreference — whether price charts draw candles instead of a line
 * (issue #152), held ONCE for every chart that asks.
 *
 * It is a display choice about how to look at prices, not a view of the data:
 * it names no ticker and no window, so it does not belong in the URL (which
 * is where a view of the data lives) and would only clutter a Share Link.
 * It follows the person instead - `localStorage`, one key, absent while off,
 * so the default needs nothing stored and a stale value cannot outlive the
 * feature being switched off.
 *
 * Three rules, each the answer to a way this could quietly go wrong:
 *
 * - **One switch means one store.** `StockPopup` opens over the fund card,
 *   and turning candles on in the popup has to change the card behind it
 *   now, not the next time it mounts. Every chart reads this and listens to
 *   it; a copy of the value in a component would make three switches that
 *   happen to save to the same key.
 * - **Storage failure never breaks the switch** (the same rule as
 *   `portfolioStorage`, principle 3 in the portfolio guide). Reading
 *   `window.localStorage` is itself what throws when site data is blocked, so
 *   every access is inside a `try`, and a refused write keeps the choice for
 *   the session and says so through `set`'s return value rather than
 *   throwing.
 * - **A change from another tab arrives without being written back.** That
 *   tab already wrote it; echoing it would only start a loop.
 *
 * The storage is passed in so none of this needs a browser to be tested;
 * `hooks/useCandles.js` is the thin wrapper that hands it the real one.
 */

export const CANDLES_KEY = 'market-analyser.chart-style';
const ON = 'candles';

/**
 * A preference over `storage` (anything with `getItem`/`setItem`/`removeItem`,
 * or null when there is none): `{ get, set, subscribe, handleStorageEvent }`.
 */
export function createCandlePreference(storage) {
  let value = null; // read lazily, so a store made at import time touches nothing
  const listeners = new Set();

  function read() {
    try {
      return storage?.getItem(CANDLES_KEY) === ON;
    } catch {
      return false;
    }
  }

  function get() {
    if (value === null) value = read();
    return value;
  }

  function change(next) {
    if (get() === next) return;
    value = next;
    listeners.forEach((listener) => listener());
  }

  /** Switch candles on or off. Returns whether the choice was kept for next
   *  time - false when storage is missing or refused it, in which case it
   *  still holds for this session. */
  function set(on) {
    change(on);
    try {
      if (!storage) return false;
      if (on) storage.setItem(CANDLES_KEY, ON);
      else storage.removeItem(CANDLES_KEY);
      return true;
    } catch {
      return false;
    }
  }

  function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  /** Take in a `storage` event from another tab: its own key changing, or
   *  every key going at once (`key` null, site data cleared). */
  function handleStorageEvent({ key, newValue }) {
    if (key !== CANDLES_KEY && key !== null) return;
    change(key === CANDLES_KEY && newValue === ON);
  }

  return { get, set, subscribe, handleStorageEvent };
}
