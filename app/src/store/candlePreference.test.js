/**
 * candlePreference — the seam the one candle switch's rules are tested at
 * (issue #152): whether price charts draw candles, held once for every chart
 * that asks. The storage is passed in, so a blocked one can be a plain
 * object here rather than something a test has to break in a browser.
 *
 * Plain functions and inline fakes, no DOM.
 */
import { expect, test, vi } from 'vitest';
import { CANDLES_KEY, createCandlePreference } from './candlePreference';

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

test('candles are off until somebody switches them on', () => {
  expect(createCandlePreference(memoryStorage()).get()).toBe(false);
});

test('a remembered choice is read back', () => {
  const store = createCandlePreference(memoryStorage({ [CANDLES_KEY]: 'candles' }));
  expect(store.get()).toBe(true);
});

test('anything stored that is not the choice reads as off', () => {
  for (const junk of ['line', '', 'true', '{"a":1}']) {
    expect(createCandlePreference(memoryStorage({ [CANDLES_KEY]: junk })).get()).toBe(false);
  }
});

// ── Switching ───────────────────────────────────────────────────────────

test('switching on is remembered, and switching off forgets rather than storing a second value', () => {
  const storage = memoryStorage();
  const store = createCandlePreference(storage);

  store.set(true);
  expect(store.get()).toBe(true);
  expect(storage.items[CANDLES_KEY]).toBe('candles');

  store.set(false);
  expect(store.get()).toBe(false);
  expect(CANDLES_KEY in storage.items).toBe(false);
});

test('every subscriber hears a change once, and nothing when nothing changed', () => {
  const store = createCandlePreference(memoryStorage());
  const fundCard = vi.fn();
  const popup = vi.fn();
  store.subscribe(fundCard);
  store.subscribe(popup);

  store.set(true);
  store.set(true);

  expect(fundCard).toHaveBeenCalledTimes(1);
  expect(popup).toHaveBeenCalledTimes(1);
});

test('a chart that has gone away stops being told', () => {
  const store = createCandlePreference(memoryStorage());
  const listener = vi.fn();
  const unsubscribe = store.subscribe(listener);
  unsubscribe();

  store.set(true);

  expect(listener).not.toHaveBeenCalled();
});

// ── Storage that cannot be trusted ──────────────────────────────────────

test('storage that throws still lets the switch work for the session', () => {
  const store = createCandlePreference(brokenStorage());
  const listener = vi.fn();
  store.subscribe(listener);

  expect(store.get()).toBe(false);
  expect(() => store.set(true)).not.toThrow();
  expect(store.get()).toBe(true);
  expect(listener).toHaveBeenCalledTimes(1);
});

test('no storage at all works the same way', () => {
  const store = createCandlePreference(null);
  store.set(true);
  expect(store.get()).toBe(true);
});

test('set says whether the choice was kept for next time', () => {
  expect(createCandlePreference(memoryStorage()).set(true)).toBe(true);
  expect(createCandlePreference(brokenStorage()).set(true)).toBe(false);
  expect(createCandlePreference(null).set(true)).toBe(false);
});

// ── Another tab ─────────────────────────────────────────────────────────

test("another tab's change arrives without being written back", () => {
  const storage = memoryStorage();
  const store = createCandlePreference(storage);
  const listener = vi.fn();
  store.subscribe(listener);

  store.handleStorageEvent({ key: CANDLES_KEY, newValue: 'candles' });

  expect(store.get()).toBe(true);
  expect(listener).toHaveBeenCalledTimes(1);
  // The other tab already wrote it; echoing it would only invite a loop.
  expect(storage.items).toEqual({});
});

test("another tab clearing the choice, or all site data, switches candles off", () => {
  const store = createCandlePreference(memoryStorage({ [CANDLES_KEY]: 'candles' }));
  store.get();

  store.handleStorageEvent({ key: CANDLES_KEY, newValue: null });
  expect(store.get()).toBe(false);

  store.set(true);
  store.handleStorageEvent({ key: null, newValue: null });
  expect(store.get()).toBe(false);
});

test("another tab's unrelated keys are none of this store's business", () => {
  const store = createCandlePreference(memoryStorage());
  const listener = vi.fn();
  store.subscribe(listener);

  store.handleStorageEvent({ key: 'market-analyser.portfolios', newValue: '[]' });

  expect(listener).not.toHaveBeenCalled();
  expect(store.get()).toBe(false);
});
