import { describe, it, expect } from 'vitest';
import { computeLayout } from './layout';

// Golden positions captured from the implementation before its force
// simulation was extracted into forceLayout.js (issue #173), so that the
// extraction is provably a move and not a change: the normal network graph must
// draw exactly the layout it always has.
const HOLDINGS = [['AAA', 30], ['BBB', 20], ['CCC', 10], ['DDD', 5], ['EEE', 1], ['FFF', 0.5]];
const MATRIX = {
  AAA: { AAA: 1, BBB: 0.9, CCC: 0.5, DDD: 0.1, EEE: null, FFF: 0.7 },
  BBB: { AAA: 0.9, BBB: 1, CCC: 0.6, DDD: 0.2, EEE: 0.3, FFF: 0.4 },
  CCC: { AAA: 0.5, BBB: 0.6, CCC: 1, DDD: 0.8, EEE: 0.35, FFF: null },
  DDD: { AAA: 0.1, BBB: 0.2, CCC: 0.8, DDD: 1, EEE: 0.85, FFF: 0.3 },
  EEE: { AAA: null, BBB: 0.3, CCC: 0.35, DDD: 0.85, EEE: 1, FFF: 0.6 },
  FFF: { AAA: 0.7, BBB: 0.4, CCC: null, DDD: 0.3, EEE: 0.6, FFF: 1 },
};

const rounded = (layout) =>
  Object.fromEntries(Object.entries(layout).map(([t, p]) => [t, [Math.round(p.x * 100) / 100, Math.round(p.y * 100) / 100]]));

describe('computeLayout', () => {
  it('places a matrix-driven graph where it always has', () => {
    expect(rounded(computeLayout('GOLD', HOLDINGS, MATRIX, 800, 500, 40))).toEqual({
      AAA: [671.78, 322.33], BBB: [540.26, 460], CCC: [305.07, 418.16],
      DDD: [40, 325.04], EEE: [128.15, 40], FFF: [760, 147.22],
    });
  });

  it('places a graph with no matrix yet by repulsion alone, round the box', () => {
    expect(rounded(computeLayout('GOLD2', HOLDINGS, undefined, 400, 400, 20))).toEqual({
      AAA: [380, 200], BBB: [290, 380], CCC: [110, 380],
      DDD: [20, 200], EEE: [110, 20], FFF: [290, 20],
    });
  });

  it('keeps every node at least `margin` from the box edge', () => {
    const out = computeLayout('GOLD3', HOLDINGS, MATRIX, 800, 500, 40);
    for (const p of Object.values(out)) {
      expect(p.x).toBeGreaterThanOrEqual(40);
      expect(p.x).toBeLessThanOrEqual(760);
      expect(p.y).toBeGreaterThanOrEqual(40);
      expect(p.y).toBeLessThanOrEqual(460);
    }
  });
});
