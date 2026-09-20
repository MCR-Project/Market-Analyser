/**
 * candles — the seam the candle view's rules are tested at (issue #152):
 * `toCandles`, given the rows `/api/series` answered and the chart's
 * timeframe, says which candles a chart draws; `candleLabel` says how a
 * candle's span reads in its tooltip.
 *
 * Plain functions and inline data, no DOM. A row is written the way the API
 * sends it - oldest first, `granularity` D/W/M, a coarse row dated by its
 * bucket anchor (the Monday of the ISO week, the 1st of the month).
 */
import { expect, test } from 'vitest';
import {
  PLOT_PAD,
  PLOT_WIDTH,
  candleCentre,
  candleIndexAt,
  candleLabel,
  candleSpan,
  toCandles,
} from './candles';

/** A row as the API sends it. */
function row(date, open, high, low, close, granularity = 'D') {
  return { date, open, high, low, close, volume: 1, granularity };
}

// 2026-03-02 is a Monday.
const WEEK_1 = [
  row('2026-03-02', 10, 12, 9, 11),
  row('2026-03-03', 11, 15, 10, 14),
  row('2026-03-04', 14, 14.5, 8, 9),
  row('2026-03-05', 9, 10, 8.5, 9.5),
  row('2026-03-06', 9.5, 11, 9, 10.5),
];
const WEEK_2 = [
  row('2026-03-09', 10.5, 11, 10, 10.8),
  row('2026-03-10', 10.8, 13, 10.6, 12.9),
];

// ── What a timeframe's candle covers ────────────────────────────────────

test('each timeframe has one span, and an unknown one reads like the 1Y default', () => {
  expect(candleSpan('1W')).toBe('day');
  expect(candleSpan('1M')).toBe('day');
  expect(candleSpan('1Y')).toBe('week');
  expect(candleSpan('5Y')).toBe('month');
  expect(candleSpan('MAX')).toBe(candleSpan('1Y'));
});

test('a day span draws one candle per row, as the row says', () => {
  const candles = toCandles(WEEK_1, '1M');
  expect(candles).toHaveLength(5);
  expect(candles[1]).toEqual({
    from: '2026-03-03', to: '2026-03-03',
    open: 11, high: 15, low: 10, close: 14, complete: true,
  });
});

test('a week span folds days into their week: first open, highest high, lowest low, last close', () => {
  const [week1, week2] = toCandles([...WEEK_1, ...WEEK_2], '1Y');
  expect(week1).toEqual({
    from: '2026-03-02', to: '2026-03-06',
    open: 10, high: 15, low: 8, close: 10.5, complete: true,
  });
  expect(week2.open).toBe(10.5);
  expect(week2.close).toBe(12.9);
});

test('a month span folds days into their month', () => {
  const rows = [
    row('2026-02-27', 5, 6, 4, 5.5),
    row('2026-03-02', 5.5, 8, 5, 7),
    row('2026-03-31', 7, 9, 6.5, 8),
  ];
  const [feb, mar] = toCandles(rows, '5Y');
  expect(feb).toMatchObject({ from: '2026-02-27', to: '2026-02-27', open: 5, close: 5.5 });
  expect(mar).toMatchObject({ from: '2026-03-02', to: '2026-03-31', open: 5.5, high: 9, low: 5, close: 8 });
});

// ── Stored coarse rows ──────────────────────────────────────────────────

test('a stored weekly row is one week candle, covering its Monday to Friday', () => {
  const candles = toCandles([row('2026-03-02', 10, 15, 8, 10.5, 'W')], '1Y');
  expect(candles).toEqual([
    { from: '2026-03-02', to: '2026-03-06', open: 10, high: 15, low: 8, close: 10.5, complete: true },
  ]);
});

test('weekly rows and the daily rows after them meet in the same series', () => {
  // A 1Y window: the old end is stored weekly, the recent end daily.
  const rows = [row('2026-03-02', 10, 15, 8, 10.5, 'W'), ...WEEK_2];
  const candles = toCandles(rows, '1Y');
  expect(candles.map((c) => [c.from, c.to])).toEqual([
    ['2026-03-02', '2026-03-06'],
    ['2026-03-09', '2026-03-10'],
  ]);
});

test('a week straddling a month end belongs to the month its Monday is in, and says so', () => {
  // 2026-03-30 is a Monday; that week ends on Friday 2026-04-03.
  const rows = [
    row('2026-03-02', 5, 6, 4, 5.5, 'W'),
    row('2026-03-30', 6, 9, 5.5, 8, 'W'),
    row('2026-04-06', 8, 9.5, 7, 9, 'W'),
  ];
  const [march, april] = toCandles(rows, '5Y');
  expect(march).toMatchObject({ from: '2026-03-02', to: '2026-04-03', open: 5, close: 8, high: 9 });
  expect(april).toMatchObject({ from: '2026-04-06', to: '2026-04-10', close: 9 });
});

test('a stored monthly row covers its whole month, a leap February included', () => {
  const [feb] = toCandles([row('2024-02-01', 1, 3, 0.5, 2, 'M')], '5Y');
  expect(feb).toMatchObject({ from: '2024-02-01', to: '2024-02-29', complete: true });
});

// ── The edges of a window ───────────────────────────────────────────────

test('a still-forming newest week and a window-clipped oldest week are both drawn, covering what they hold', () => {
  // The window opens on a Wednesday and ends on a Tuesday.
  const rows = [
    row('2026-03-04', 14, 14.5, 8, 9),
    row('2026-03-05', 9, 10, 8.5, 9.5),
    row('2026-03-09', 10.5, 11, 10, 10.8),
    row('2026-03-10', 10.8, 13, 10.6, 12.9),
  ];
  const [oldest, newest] = toCandles(rows, '1Y');
  expect(oldest).toMatchObject({ from: '2026-03-04', to: '2026-03-05', open: 14 });
  expect(newest).toMatchObject({ from: '2026-03-09', to: '2026-03-10', close: 12.9 });
});

test('a window holding a single stretch draws that one candle', () => {
  expect(toCandles(WEEK_2, '5Y')).toHaveLength(1);
  expect(toCandles([WEEK_2[0]], '1M')).toHaveLength(1);
});

test('nothing to draw is an empty list, never an error', () => {
  expect(toCandles([], '1Y')).toEqual([]);
  expect(toCandles(null, '1Y')).toEqual([]);
  expect(toCandles(undefined, '1Y')).toEqual([]);
});

// ── Absence is a gap, never a flat candle ───────────────────────────────

test('a candle missing any of open, high or low is a gap: nulls in place, the close still known', () => {
  for (const missing of ['open', 'high', 'low']) {
    const broken = { ...row('2026-03-03', 11, 15, 10, 14), [missing]: null };
    const [candle] = toCandles([broken], '1M');
    expect(candle).toEqual({
      from: '2026-03-03', to: '2026-03-03',
      open: null, high: null, low: null, close: 14, complete: false,
    });
  }
});

test('a missing close is a gap too, not a candle drawn from nothing', () => {
  const [candle] = toCandles([{ ...row('2026-03-03', 11, 15, 10, 14), close: null }], '1M');
  expect(candle).toMatchObject({ open: null, high: null, low: null, close: null, complete: false });
});

test('rows from before the API sent open/high/low read as gaps, not as zeros', () => {
  const [candle] = toCandles([{ date: '2026-03-03', close: 14, volume: 1, granularity: 'D' }], '1M');
  expect(candle).toMatchObject({ open: null, high: null, low: null, close: 14, complete: false });
});

test('one day missing a price makes its whole week a gap, and only that week', () => {
  // The week's high is unknown without that day's; a smaller number would
  // be a range nobody measured.
  const days = [...WEEK_1];
  days[2] = { ...days[2], high: null };
  const [week1, week2] = toCandles([...days, ...WEEK_2], '1Y');
  expect(week1).toMatchObject({ high: null, open: null, low: null, close: 10.5, complete: false });
  expect(week2.complete).toBe(true);
});

test('a price of zero is a price, not an absence', () => {
  const [candle] = toCandles([row('2026-03-03', 0, 1, 0, 0.5)], '1M');
  expect(candle).toMatchObject({ open: 0, low: 0, complete: true });
});

test('the rows given are left as they were', () => {
  const rows = structuredClone(WEEK_1);
  toCandles(rows, '1Y');
  expect(rows).toEqual(WEEK_1);
});

// ── How a span reads in the tooltip ─────────────────────────────────────

test('a one-day candle reads as that day', () => {
  const [candle] = toCandles([WEEK_1[0]], '1M');
  expect(candleLabel(candle)).toBe('Mar 2, 2026');
});

test('a longer candle reads as the days it covers, with the year once when it is shared', () => {
  const [week] = toCandles(WEEK_1, '1Y');
  expect(candleLabel(week)).toBe('Mar 2 – Mar 6, 2026');
});

test('a candle spanning a year end names both years', () => {
  const rows = [row('2025-12-29', 1, 2, 1, 2), row('2026-01-02', 2, 3, 2, 3)];
  const [week] = toCandles(rows, '1Y');
  expect(candleLabel(week)).toBe('Dec 29, 2025 – Jan 2, 2026');
});

// ── Where a candle sits ─────────────────────────────────────────────────
// The chart draws candles and the hover hook finds them from the cursor; both
// read these two functions, so they cannot disagree about which candle is
// where.

test('candles sit in even slots inside the plot, and a lone one is centred', () => {
  expect(candleCentre(0, 1)).toBe(PLOT_WIDTH / 2);

  const centres = Array.from({ length: 60 }, (_, i) => candleCentre(i, 60));
  expect(centres[0]).toBeGreaterThan(PLOT_PAD);
  expect(centres[59]).toBeLessThan(PLOT_WIDTH - PLOT_PAD);
  const gap = centres[1] - centres[0];
  centres.slice(1).forEach((c, i) => expect(c - centres[i]).toBeCloseTo(gap, 9));
});

test('the candle under a candle centre is that candle, however many there are', () => {
  for (const count of [1, 2, 5, 52, 60]) {
    for (let i = 0; i < count; i += 1) {
      expect(candleIndexAt(candleCentre(i, count), count)).toBe(i);
    }
  }
});

test('a cursor beyond either end of the plot lands on the nearest candle', () => {
  expect(candleIndexAt(-40, 5)).toBe(0);
  expect(candleIndexAt(PLOT_WIDTH + 40, 5)).toBe(4);
});
