/**
 * presetWindow — the seam the window presets are tested at (issue #156): what
 * each button means in dates. The stretches count back from today by the same
 * day counts as the backend's PERIOD_TO_DAYS (30, 90, 182, 365, 1825), so a
 * preset asks for the stretch the backend would have counted itself.
 *
 * The date is passed in, so every expected value is a literal that can be
 * checked against a calendar and nothing needs a fake clock.
 *
 * Plain functions and inline data, no DOM.
 */
import { expect, test } from 'vitest';
import { PRESETS, presetWindow } from './windowPresets';

const NOON = new Date('2026-09-21T12:00:00Z');

test('the short presets count back 30, 90 and 182 days from today', () => {
  expect(presetWindow('1m', NOON)).toEqual({ start: '2026-08-22', end: '2026-09-21' });
  expect(presetWindow('3m', NOON)).toEqual({ start: '2026-06-23', end: '2026-09-21' });
  expect(presetWindow('6m', NOON)).toEqual({ start: '2026-03-23', end: '2026-09-21' });
});

test('the presets that already existed still mean what they did', () => {
  expect(presetWindow('1y', NOON)).toEqual({ start: '2025-09-21', end: '2026-09-21' });
  expect(presetWindow('5y', NOON)).toEqual({ start: '2021-09-22', end: '2026-09-21' });
  expect(presetWindow('ytd', NOON)).toEqual({ start: '2026-01-01', end: '2026-09-21' });
});

test('every preset reads the UTC calendar, the one an end is checked against', () => {
  // Half an hour before 1 January in UTC is already 1 January in Paris, so a
  // local-year YTD next to a UTC "today" would start after it ends.
  const lateEvening = new Date('2025-12-31T23:30:00Z');
  expect(presetWindow('ytd', lateEvening)).toEqual({ start: '2025-01-01', end: '2025-12-31' });
  expect(presetWindow('1m', lateEvening)).toEqual({ start: '2025-12-01', end: '2025-12-31' });
});

test('max has no dates of its own: the basket decides how far back it goes', () => {
  expect(presetWindow('max', NOON)).toEqual({ period: 'max', start: null, end: null });
});

test('the buttons run shortest to longest, with YTD and Max last', () => {
  expect(PRESETS.map(p => p.key)).toEqual(['1m', '3m', '6m', '1y', '5y', 'ytd', 'max']);
  expect(PRESETS.map(p => p.label)).toEqual(['1M', '3M', '6M', '1Y', '5Y', 'YTD', 'Max']);
});
