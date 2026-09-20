/**
 * chartTooltip — the seam the price charts' hover readout is tested at
 * (issue #152): `buildTooltip`, given a hovered index over a chart's closes
 * (and, for a candle chart, its candles), says what the tooltip shows and
 * where. A line chart's readout is pinned here too, so the candle view can
 * never quietly change it.
 *
 * Plain functions and inline data, no DOM.
 */
import { expect, test } from 'vitest';
import { buildTooltip } from './chartTooltip';
import { toCandles } from './candles';

function row(date, open, high, low, close, granularity = 'D') {
  return { date, open, high, low, close, volume: 1, granularity };
}

const ROWS = [
  row('2026-03-02', 10, 12, 9, 11),
  row('2026-03-03', 11, 15, 10, 14),
  row('2026-03-04', 14, 14.5, 8, 9),
  row('2026-03-09', 9, 10, 8.5, 12),
];
const CLOSES = ROWS.map((r) => r.close);
const DATES = ROWS.map((r) => r.date);

// ── The line ────────────────────────────────────────────────────────────

test('over the line: the day, its close, and the return since the first close', () => {
  const tip = buildTooltip({ arr: CLOSES, hoverIdx: 1, dates: DATES });
  expect(tip).toMatchObject({
    label: 'Mar 3, 2026',
    formattedValue: '$14.00',
    returnPct: '+27.27%',
    runPos: true,
    candle: null,
  });
});

test('a fall since the start reads negative', () => {
  const tip = buildTooltip({ arr: CLOSES, hoverIdx: 2, dates: DATES });
  expect(tip).toMatchObject({ returnPct: '-18.18%', runPos: false });
});

test('the tooltip flips to the left of the cursor past the middle of the chart', () => {
  expect(buildTooltip({ arr: CLOSES, hoverIdx: 0, dates: DATES }).alignRight).toBe(false);
  expect(buildTooltip({ arr: CLOSES, hoverIdx: 3, dates: DATES }).alignRight).toBe(true);
});

test('a point with no value has nothing to read out', () => {
  // A candle with no close at all (a gap with nothing behind it) must not
  // reach the price formatter, which would throw on it.
  expect(buildTooltip({ arr: [11, null, 9], hoverIdx: 1, dates: DATES })).toBeNull();
});

test('no hover, or a hover past the data, is no tooltip', () => {
  expect(buildTooltip({ arr: CLOSES, hoverIdx: null, dates: DATES })).toBeNull();
  expect(buildTooltip({ arr: CLOSES, hoverIdx: 9, dates: DATES })).toBeNull();
  expect(buildTooltip({ arr: null, hoverIdx: 0, dates: null })).toBeNull();
});

// ── The candle ──────────────────────────────────────────────────────────

test('over a candle: the days it covers and all four prices', () => {
  const candles = toCandles(ROWS, '1Y'); // two weeks
  const tip = buildTooltip({
    arr: candles.map((c) => c.close), hoverIdx: 0, candleView: { candles, base: CLOSES[0] },
  });
  expect(tip.label).toBe('Mar 2 – Mar 4, 2026');
  expect(tip.candle).toEqual({
    complete: true, open: '$10.00', high: '$15.00', low: '$8.00', close: '$9.00',
  });
});

test("a candle's return is measured from the first row's close, the figure the chart header uses", () => {
  // The first candle's own close is 9; the header's base is the first row's 11.
  const candles = toCandles(ROWS, '1Y');
  const tip = buildTooltip({
    arr: candles.map((c) => c.close), hoverIdx: 1, candleView: { candles, base: CLOSES[0] },
  });
  expect(tip.returnPct).toBe('+9.09%'); // 12 against 11, not against 9
});

test('over a gap: no prices claimed, the close it does have still shown', () => {
  const broken = [ROWS[0], { ...ROWS[1], high: null }, ROWS[2]];
  const candles = toCandles(broken, '1M');
  const tip = buildTooltip({
    arr: candles.map((c) => c.close), hoverIdx: 1, candleView: { candles, base: 11 },
  });
  expect(tip.candle).toEqual({
    complete: false, open: null, high: null, low: null, close: '$14.00',
  });
  expect(tip.formattedValue).toBe('$14.00');
});

test('a candle tooltip sits on its own slot, not on a line point', () => {
  const candles = toCandles(ROWS, '1M'); // four one-day candles
  const line = buildTooltip({ arr: CLOSES, hoverIdx: 0, dates: DATES });
  const candle = buildTooltip({
    arr: CLOSES, hoverIdx: 0, candleView: { candles, base: CLOSES[0] },
  });
  // A line's first point is at the plot's left edge; a candle's centre is
  // half a slot in, so its tooltip starts further along.
  expect(candle.pctX).toBeGreaterThan(line.pctX);
});
