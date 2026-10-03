import { test, expect } from 'vitest';
import { pairInsights } from './pairInsights';

// A symmetric matrix the way GET /api/correlation answers it: matrix[a][b].
function matrixOf(pairs, tickers) {
  const m = Object.fromEntries(tickers.map(t => [t, { [t]: 1 }]));
  for (const [a, b, v] of pairs) { m[a][b] = v; m[b][a] = v; }
  return m;
}

const tickers = ['AAA', 'BBB', 'CCC', 'U1'];
const matrix = matrixOf([
  ['AAA', 'BBB', 0.5], ['AAA', 'CCC', 0.2], ['BBB', 'CCC', -0.1],
  ['U1', 'AAA', 0.99], ['U1', 'BBB', 0.9], ['U1', 'CCC', -0.8],
], tickers);

test('the strongest and loosest pair and the hub, over the tickers it is given', () => {
  const r = pairInsights(matrix, ['AAA', 'BBB', 'CCC']);
  expect(r.strongest).toEqual({ a: 'AAA', b: 'BBB', value: 0.5 });
  expect(r.weakest).toEqual({ a: 'BBB', b: 'CCC', value: -0.1 });
  expect(r.hub.ticker).toBe('AAA');
  expect(r.hub.avgCorr).toBeCloseTo(0.35, 4);
});

test('a ticker left out takes its pairs with it: the answer is not the whole matrix\'s', () => {
  expect(pairInsights(matrix, tickers).strongest).toEqual({ a: 'AAA', b: 'U1', value: 0.99 });
  expect(pairInsights(matrix, ['AAA', 'BBB', 'CCC']).strongest.a).not.toBe('U1');
  expect(pairInsights(matrix, ['AAA', 'BBB', 'CCC']).strongest.b).not.toBe('U1');
});

test('an unknown pair is not a candidate and is not read as zero', () => {
  const m = matrixOf([['AAA', 'BBB', 0.4]], ['AAA', 'BBB', 'CCC']);
  m.AAA.CCC = null; m.CCC.AAA = null;
  const r = pairInsights(m, ['AAA', 'BBB', 'CCC']);
  expect(r.strongest).toEqual({ a: 'AAA', b: 'BBB', value: 0.4 });
  expect(r.weakest).toEqual({ a: 'AAA', b: 'BBB', value: 0.4 });
  expect(r.hub.ticker).not.toBe('CCC');
});

test('nothing to report is null, never a made-up value', () => {
  expect(pairInsights(matrix, ['AAA'])).toEqual({ strongest: null, weakest: null, hub: null });
  expect(pairInsights({}, ['AAA', 'BBB'])).toEqual({ strongest: null, weakest: null, hub: null });
  expect(pairInsights(undefined, ['AAA', 'BBB'])).toEqual({ strongest: null, weakest: null, hub: null });
});
