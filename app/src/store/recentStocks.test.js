/**
 * recentStocks — the seam the Stock page's recently-viewed sidebar (issue
 * #158) is tested at: which tickers were opened, most recent first, capped
 * at MAX_RECENT_STOCKS. Storage is passed in, the same way
 * candlePreference.test.js's fakes stand in for a browser.
 *
 * Plain functions and inline fakes, no DOM.
 */
import { expect, test, vi } from 'vitest';
import { MAX_RECENT_STOCKS, RECENT_STOCKS_KEY, createRecentStocks } from './recentStocks';

/** A storage that works, and remembers what it was asked. */
function memoryStorage(initial = {}) {
  const items = { ...initial };
  return {
    items,
    getItem: (key) => (key in items ? items[key] : null),
    setItem: (key, value) => { items[key] = String(value); },
    removeItem: (key) => { delete items[key]; },
  };
}

/** A storage that throws on every call - site data blocked, a private
 *  window, a full quota. */
function brokenStorage() {
  const fail = () => { throw new Error('storage is blocked'); };
  return { getItem: fail, setItem: fail, removeItem: fail };
}

// ── The default, and what was remembered ────────────────────────────────

test('nothing has been viewed until a stock is opened', () => {
  expect(createRecentStocks(memoryStorage()).get()).toEqual([]);
});

test('a remembered list is read back', () => {
  const store = createRecentStocks(memoryStorage({ [RECENT_STOCKS_KEY]: '["NVDA","TSLA"]' }));
  expect(store.get()).toEqual(['NVDA', 'TSLA']);
});

test('anything stored that is not a list of strings reads as empty', () => {
  for (const junk of ['not json', '{"a":1}', '"NVDA"', '[1,2,3]', '[null]', '']) {
    expect(createRecentStocks(memoryStorage({ [RECENT_STOCKS_KEY]: junk })).get()).toEqual([]);
  }
});

// ── Adding a visit ──────────────────────────────────────────────────────

test('opening a stock puts it at the front', () => {
  const store = createRecentStocks(memoryStorage());
  store.add('NVDA');
  store.add('TSLA');
  expect(store.get()).toEqual(['TSLA', 'NVDA']);
});

test('re-opening an already-listed stock moves it to the front instead of duplicating it', () => {
  const store = createRecentStocks(memoryStorage());
  store.add('NVDA');
  store.add('TSLA');
  store.add('AMD');
  store.add('NVDA');
  expect(store.get()).toEqual(['NVDA', 'AMD', 'TSLA']);
});

test('symbols are normalised, so the same stock never appears twice under a different case', () => {
  const store = createRecentStocks(memoryStorage());
  store.add('nvda');
  store.add(' Nvda ');
  expect(store.get()).toEqual(['NVDA']);
});

test('a blank symbol changes nothing', () => {
  const store = createRecentStocks(memoryStorage());
  store.add('NVDA');
  store.add('   ');
  expect(store.get()).toEqual(['NVDA']);
});

test(`the list is capped at ${MAX_RECENT_STOCKS}, oldest dropped first`, () => {
  const store = createRecentStocks(memoryStorage());
  for (let i = 0; i < MAX_RECENT_STOCKS + 3; i++) store.add(`T${i}`);

  const list = store.get();
  expect(list).toHaveLength(MAX_RECENT_STOCKS);
  expect(list[0]).toBe(`T${MAX_RECENT_STOCKS + 2}`);
  expect(list).not.toContain('T0');
  expect(list).not.toContain('T1');
  expect(list).not.toContain('T2');
});

test('a visit is written to storage as it is read back', () => {
  const storage = memoryStorage();
  createRecentStocks(storage).add('NVDA');
  expect(storage.items[RECENT_STOCKS_KEY]).toBe('["NVDA"]');
});

// ── Subscribers ─────────────────────────────────────────────────────────

test('every subscriber hears a visit once', () => {
  const store = createRecentStocks(memoryStorage());
  const sidebar = vi.fn();
  const other = vi.fn();
  store.subscribe(sidebar);
  store.subscribe(other);

  store.add('NVDA');

  expect(sidebar).toHaveBeenCalledTimes(1);
  expect(other).toHaveBeenCalledTimes(1);
});

test('a sidebar that has gone away stops being told', () => {
  const store = createRecentStocks(memoryStorage());
  const listener = vi.fn();
  const unsubscribe = store.subscribe(listener);
  unsubscribe();

  store.add('NVDA');

  expect(listener).not.toHaveBeenCalled();
});

// ── Storage that cannot be trusted ──────────────────────────────────────

test('storage that throws still lets the list work for the session', () => {
  const store = createRecentStocks(brokenStorage());
  const listener = vi.fn();
  store.subscribe(listener);

  expect(() => store.add('NVDA')).not.toThrow();
  expect(store.get()).toEqual(['NVDA']);
  expect(listener).toHaveBeenCalledTimes(1);
});

test('no storage at all works the same way', () => {
  const store = createRecentStocks(null);
  store.add('NVDA');
  expect(store.get()).toEqual(['NVDA']);
});

// ── Another tab ─────────────────────────────────────────────────────────

test("another tab's change arrives without being written back", () => {
  const storage = memoryStorage();
  const store = createRecentStocks(storage);
  const listener = vi.fn();
  store.subscribe(listener);

  store.handleStorageEvent({ key: RECENT_STOCKS_KEY, newValue: '["AMD"]' });

  expect(store.get()).toEqual(['AMD']);
  expect(listener).toHaveBeenCalledTimes(1);
  // The other tab already wrote it; echoing it would only invite a loop.
  expect(storage.items).toEqual({});
});

test('another tab clearing all site data empties the list', () => {
  const store = createRecentStocks(memoryStorage({ [RECENT_STOCKS_KEY]: '["NVDA"]' }));
  store.get();

  store.handleStorageEvent({ key: null, newValue: null });

  expect(store.get()).toEqual([]);
});

test("another tab's unrelated keys are none of this store's business", () => {
  const store = createRecentStocks(memoryStorage());
  const listener = vi.fn();
  store.subscribe(listener);

  store.handleStorageEvent({ key: 'market-analyser.portfolios', newValue: '[]' });

  expect(listener).not.toHaveBeenCalled();
  expect(store.get()).toEqual([]);
});
