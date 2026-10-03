import { test, expect } from 'vitest';
import { trackedHoldings } from './trackedHoldings';

const holdings = [['AAA', 30], ['BBB', 20], ['U1', 0.9], ['U2', 0.8]];

test('a fund that is not deep-filled is returned as it is', () => {
  expect(trackedHoldings(holdings, undefined)).toBe(holdings);
  expect(trackedHoldings(holdings, [])).toBe(holdings);
});

test('a deep-filled fund loses its untracked holdings, order and weights kept', () => {
  expect(trackedHoldings(holdings, ['U1', 'U2'])).toEqual([['AAA', 30], ['BBB', 20]]);
});

test('naming a holding the list does not have changes nothing', () => {
  expect(trackedHoldings(holdings, ['ZZZ'])).toEqual(holdings);
});

test('no list yet is no holdings', () => {
  expect(trackedHoldings(undefined, ['U1'])).toEqual([]);
  expect(trackedHoldings(null, undefined)).toEqual([]);
});
