import { describe, it, expect } from 'vitest';
import { decodeFullView, fmtWeight } from './fullView';

const payload = (over = {}) => ({
  etfId: 'FAKE',
  period: '1y',
  asOf: '2026-10-02T09:30:00Z',
  expiresAt: '2026-10-03T09:30:00Z',
  tickers: ['AAA', 'BBB', 'CCC'],
  weights: [30, 20, 0.5],
  averages: [0.5, 0.4, null],
  clusters: [['AAA', 'BBB']],
  correlation: { decimals: 2, triangle: [[], [0.62], [null, 0.1]] },
  excluded: { ZZZ: 'it could not be fetched' },
  ...over,
});

describe('decodeFullView', () => {
  it('rebuilds the whole square from the lower triangle', () => {
    const view = decodeFullView(payload());

    expect(view.n).toBe(3);
    expect(view.at(0, 0)).toBe(1);
    expect(view.at(1, 0)).toBeCloseTo(0.62);
    expect(view.at(0, 1)).toBeCloseTo(0.62);      // symmetric
    expect(view.at(2, 1)).toBeCloseTo(0.1);
    expect(view.at(1, 2)).toBeCloseTo(0.1);
  });

  it('keeps a pair with no correlation as null, never as a number', () => {
    const view = decodeFullView(payload());

    expect(view.at(2, 0)).toBeNull();
    expect(view.at(0, 2)).toBeNull();
    expect(Number.isNaN(view.corr[2])).toBe(true);   // NaN is how the typed array holds "none"
  });

  it('hands the holdings back as [ticker, weight], in the fund\'s order, and an index by ticker', () => {
    const view = decodeFullView(payload());

    expect(view.holdings).toEqual([['AAA', 30], ['BBB', 20], ['CCC', 0.5]]);
    expect(view.indexOf.get('CCC')).toBe(2);
    expect(view.indexOf.has('ZZZ')).toBe(false);
  });

  it('keeps averages by ticker, with null where a ticker has no pair at all', () => {
    expect(decodeFullView(payload()).averages).toEqual({ AAA: 0.5, BBB: 0.4, CCC: null });
  });

  it('carries the clusters, the left-out holdings and the Deep-fill\'s own times through unchanged', () => {
    const view = decodeFullView(payload());

    expect(view.clusters).toEqual([['AAA', 'BBB']]);
    expect(view.excluded).toEqual({ ZZZ: 'it could not be fetched' });
    expect(view.asOf).toBe('2026-10-02T09:30:00Z');
    expect(view.expiresAt).toBe('2026-10-03T09:30:00Z');
    expect(view.etfId).toBe('FAKE');
  });

  it('decodes a fund of one holding', () => {
    const view = decodeFullView(payload({
      tickers: ['AAA'], weights: [100], averages: [null], clusters: [],
      correlation: { decimals: 2, triangle: [[]] },
    }));
    expect(view.n).toBe(1);
    expect(view.at(0, 0)).toBe(1);
  });

  it('refuses a payload whose parts disagree, rather than drawing a wrong matrix', () => {
    expect(() => decodeFullView(payload({ weights: [30, 20] }))).toThrow(/malformed/i);
    expect(() => decodeFullView(payload({ correlation: { decimals: 2, triangle: [[], [0.6]] } }))).toThrow(/malformed/i);
    expect(() => decodeFullView(payload({ correlation: { decimals: 2, triangle: [[], [0.6, 0.1], [null, 0.1]] } }))).toThrow(/malformed/i);
    expect(() => decodeFullView(null)).toThrow(/malformed/i);
  });
});

describe('fmtWeight', () => {
  it('keeps enough places that a small holding does not read as zero', () => {
    expect(fmtWeight(7.123)).toBe('7.1%');
    expect(fmtWeight(1)).toBe('1.0%');
    expect(fmtWeight(0.456)).toBe('0.46%');
    expect(fmtWeight(0.1)).toBe('0.10%');
    expect(fmtWeight(0.0123)).toBe('0.012%');
    expect(fmtWeight(0.0004)).toBe('0.000%');
  });
});
