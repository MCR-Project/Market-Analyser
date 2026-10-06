import { describe, it, expect } from 'vitest';
import { decodeFullView } from './fullView';
import {
  arrange, cellPixels, rampIndex, cellAt, labelPlan, visibleCells, clusterBlocks,
  MATRIX_MAX_CELL_PX, matrixLimits,
} from './fullMatrix';

const decode = (over = {}) => decodeFullView({
  etfId: 'FAKE', period: '1y', asOf: 'a', expiresAt: 'b',
  tickers: ['AAA', 'BBB', 'CCC', 'DDD'],
  weights: [30, 20, 10, 5],
  averages: [0.5, 0.4, 0.3, 0.2],
  clusters: [['AAA', 'CCC']],
  correlation: { decimals: 2, triangle: [[], [0.62], [0.9, 0.1], [0.2, 0.3, 0.4]] },
  excluded: {},
  ...over,
});

describe('arrange', () => {
  it('puts a cluster\'s members side by side in cluster order, as indexes into the fund', () => {
    const fund = decode();
    const { order, sections } = arrange(fund, 'cluster', 'weight');

    expect(order.slice(0, 2)).toEqual([0, 2]);                  // AAA and CCC, heaviest first
    expect(sections[0]).toMatchObject({ kind: 'cluster', start: 0, count: 2 });
    expect([...order].sort()).toEqual([0, 1, 2, 3]);            // every holding drawn once
  });

  it('draws every holding, however many there are (no top-N)', () => {
    const fund = decode();
    expect(arrange(fund, 'weight', 'weight').order).toEqual([0, 1, 2, 3]);
    expect(arrange(fund, 'alpha', 'weight').order).toEqual([0, 1, 2, 3]);
  });

  it('bands a holding with no history apart rather than calling it uncorrelated', () => {
    const fund = decode({ averages: [0.5, 0.4, 0.3, null] });
    const { order, sections } = arrange(fund, 'cluster', 'weight');

    expect(order[order.length - 1]).toBe(3);
    expect(sections.at(-1).kind).toBe('nohistory');
  });
});

describe('rampIndex', () => {
  it('is the whole percentage of ρ, held between 0 and 100', () => {
    expect(rampIndex(0.62)).toBe(62);
    expect(rampIndex(0.999)).toBe(100);
    expect(rampIndex(1)).toBe(100);
    expect(rampIndex(0)).toBe(0);
    // cellColor reads a negative ρ as the lightest step, not as a new colour
    expect(rampIndex(-0.4)).toBe(0);
  });
});

describe('cellPixels', () => {
  const ramp = Array.from({ length: 101 }, (_, i) => [i, 0, 0]);
  const palette = { ramp, none: [7, 7, 7], diagonal: [9, 9, 9] };

  it('writes one RGBA pixel per cell, in drawing order, not data order', () => {
    const fund = decode();
    // draw DDD first, then AAA: pixel (row 0, col 1) is the DDD-AAA pair, 0.2
    const px = cellPixels([3, 0, 1, 2], fund.corr, fund.n, palette);

    expect(px).toHaveLength(4 * 4 * 4);
    const at = (r, c) => Array.from(px.slice((r * 4 + c) * 4, (r * 4 + c) * 4 + 4));
    expect(at(0, 1)).toEqual([20, 0, 0, 255]);
    expect(at(1, 0)).toEqual([20, 0, 0, 255]);                  // symmetric
  });

  it('colours the diagonal and a pair with no correlation distinctly', () => {
    const fund = decode({ correlation: { decimals: 2, triangle: [[], [null], [0.9, 0.1], [0.2, 0.3, 0.4]] } });
    const px = cellPixels([0, 1, 2, 3], fund.corr, fund.n, palette);
    const at = (r, c) => Array.from(px.slice((r * 4 + c) * 4, (r * 4 + c) * 4 + 3));

    expect(at(0, 0)).toEqual([9, 9, 9]);
    expect(at(1, 0)).toEqual([7, 7, 7]);                        // null, not ρ = 0
    expect(at(0, 1)).toEqual([7, 7, 7]);
    expect(at(2, 0)).toEqual([90, 0, 0]);
  });
});

describe('cellAt', () => {
  const view = { scale: 10, x: -20, y: 0 };

  it('finds the cell under a point of the matrix area', () => {
    expect(cellAt(view, 25, 35, 50)).toEqual({ row: 3, col: 4 });
    expect(cellAt(view, 20, 0, 50)).toEqual({ row: 0, col: 4 });
  });

  it('is null off the matrix on any side', () => {
    expect(cellAt(view, 5, 5, 50)).toEqual({ row: 0, col: 2 });
    expect(cellAt({ scale: 10, x: 30, y: 0 }, 5, 5, 50)).toBeNull();     // left of column 0
    expect(cellAt(view, 25, -1, 50)).toBeNull();
    expect(cellAt({ scale: 10, x: 0, y: 0 }, 500, 5, 50)).toBeNull();    // right of column n-1
    expect(cellAt({ scale: 10, x: 0, y: 0 }, 5, 500, 50)).toBeNull();
  });
});

describe('labelPlan', () => {
  it('shows nothing until a cell is big enough to read a label beside it', () => {
    expect(labelPlan(4)).toEqual({ labels: false, values: false, labelPx: 0, valuePx: 0 });
    expect(labelPlan(11.9).labels).toBe(false);
    expect(labelPlan(12).labels).toBe(true);
  });

  it('prints each ρ inside its cell only once it is big enough to fit "−0.12"', () => {
    expect(labelPlan(33).values).toBe(false);
    expect(labelPlan(34).values).toBe(true);
    expect(labelPlan(34).labels).toBe(true);
  });

  it('never asks for text larger than 12px for a label or 13px for a value', () => {
    const big = labelPlan(80);
    expect(big.labelPx).toBeLessThanOrEqual(12);
    expect(big.valuePx).toBeLessThanOrEqual(13);
    expect(big.labelPx).toBeGreaterThanOrEqual(9);
  });
});

describe('visibleCells', () => {
  it('is the cells the area shows, clipped to the matrix', () => {
    const range = visibleCells({ scale: 10, x: -25, y: -5 }, { w: 100, h: 50 }, 8);
    expect(range).toEqual({ r0: 0, r1: 6, c0: 2, c1: 8 });
  });

  it('is empty rather than negative when the matrix is entirely off screen', () => {
    const range = visibleCells({ scale: 10, x: 500, y: 0 }, { w: 100, h: 50 }, 8);
    expect(range.c1).toBeLessThanOrEqual(range.c0);
  });
});

describe('clusterBlocks', () => {
  it('turns the cluster sections, and only those, into squares on the diagonal', () => {
    const blocks = clusterBlocks([
      { key: 'A', kind: 'cluster', label: 'A group', start: 0, count: 3, size: 3 },
      { key: '__others', kind: 'others', label: 'Others', start: 3, count: 4, size: 4 },
      { key: 'B', kind: 'cluster', label: 'B group', start: 7, count: 2, size: 2 },
    ]);
    expect(blocks).toEqual([
      { key: 'A', label: 'A group', start: 0, count: 3 },
      { key: 'B', label: 'B group', start: 7, count: 2 },
    ]);
    expect(clusterBlocks(null)).toEqual([]);
  });
});

describe('matrixLimits', () => {
  it('lets the whole matrix fit at the bottom and a cell grow to MATRIX_MAX_CELL_PX at the top', () => {
    expect(matrixLimits({ scale: 0.8 })).toEqual({ min: 0.8, max: MATRIX_MAX_CELL_PX });
  });

  it('keeps a max above the min even for a tiny matrix whose fit is already large', () => {
    const { min, max } = matrixLimits({ scale: 500 });
    expect(max).toBeGreaterThanOrEqual(min);
  });
});
