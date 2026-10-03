import { test, expect, beforeEach } from 'vitest';
import { observeDeepFill, forgetDeepFill, deepFillEpoch, subscribeDeepFill, resetDeepFillEpochs } from './deepFillEpoch';

beforeEach(resetDeepFillEpochs);

test('a fund nothing has been observed for is at epoch 0', () => {
  expect(deepFillEpoch('SPY')).toBe(0);
});

test('the first thing seen is the baseline: a page that loads onto a deep-filled fund refetches nothing', () => {
  observeDeepFill('SPY', '2026-10-02T09:30:00+00:00');
  expect(deepFillEpoch('SPY')).toBe(0);
});

test('seeing the same answer again changes nothing', () => {
  observeDeepFill('SPY', null);
  observeDeepFill('SPY', null);
  observeDeepFill('SPY', null);
  expect(deepFillEpoch('SPY')).toBe(0);
});

test('a Deep-fill finishing moves the epoch, so what was read before is read again', () => {
  observeDeepFill('SPY', null);
  observeDeepFill('SPY', '2026-10-02T09:30:00+00:00');
  expect(deepFillEpoch('SPY')).toBe(1);
});

test('an expiry moves it too, back to the tracked-only answer', () => {
  observeDeepFill('SPY', '2026-10-02T09:30:00+00:00');
  observeDeepFill('SPY', null);
  expect(deepFillEpoch('SPY')).toBe(1);
});

test('a result redrawn while nobody was looking is a different answer', () => {
  observeDeepFill('SPY', '2026-10-02T09:30:00+00:00');
  observeDeepFill('SPY', '2026-10-03T11:00:00+00:00');
  expect(deepFillEpoch('SPY')).toBe(1);
});

test('funds are independent of one another', () => {
  observeDeepFill('SPY', null);
  observeDeepFill('QQQ', null);
  observeDeepFill('SPY', '2026-10-02T09:30:00+00:00');
  expect(deepFillEpoch('SPY')).toBe(1);
  expect(deepFillEpoch('QQQ')).toBe(0);
});

test('a fund the page stopped watching is looked at afresh when it comes back', () => {
  // On SPY while it is deep-filled, away past its expiry, then back: the page's
  // own requests on return already got the tracked-only answer, so the first
  // status (asOf null) is a new baseline, not a change from the old one.
  observeDeepFill('SPY', '2026-10-02T09:30:00+00:00');
  forgetDeepFill('SPY');
  observeDeepFill('SPY', null);
  expect(deepFillEpoch('SPY')).toBe(0);
});

test('a subscriber hears about a change, and only a change', () => {
  let heard = 0;
  const unsubscribe = subscribeDeepFill(() => { heard += 1; });

  observeDeepFill('SPY', null);                               // baseline
  observeDeepFill('SPY', null);                               // nothing new
  expect(heard).toBe(0);

  observeDeepFill('SPY', '2026-10-02T09:30:00+00:00');
  expect(heard).toBe(1);

  unsubscribe();
  observeDeepFill('SPY', null);
  expect(heard).toBe(1);
});
