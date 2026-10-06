import { describe, it, expect } from 'vitest';
import { decodeFullView } from './fullView';
import {
  NETWORK_WORLD, NODE_LABEL_MIN_PX, DEFAULT_THRESHOLD, THRESHOLD_MIN, THRESHOLD_MAX,
  nodeRadius, rankedLinks, linksAtLeast, edgeBands, neighboursOf, hitNode, labelShown, networkLimits,
} from './fullNetwork';
import { layoutFullNetwork } from './fullNetworkLayout';

const fund = decodeFullView({
  etfId: 'FAKE', period: '1y', asOf: 'a', expiresAt: 'b',
  tickers: ['A', 'B', 'C', 'D', 'E'],
  weights: [30, 20, 10, 5, 1],
  averages: [0, 0, 0, 0, 0],
  clusters: [],
  correlation: {
    decimals: 2,
    triangle: [
      [],
      [0.9],
      [0.5, 0.75],
      [0.1, null, 0.8],
      [0.25, 0.3, 0.2, 0.95],
    ],
  },
  excluded: {},
});

describe('constants', () => {
  it('starts the Link Threshold at 0.5, inside the slider\'s own range', () => {
    expect(DEFAULT_THRESHOLD).toBe(0.5);
    expect(THRESHOLD_MIN).toBeLessThan(DEFAULT_THRESHOLD);
    expect(THRESHOLD_MAX).toBeGreaterThan(DEFAULT_THRESHOLD);
  });
});

describe('nodeRadius', () => {
  it('grows with weight and stays inside its bounds', () => {
    expect(nodeRadius(0)).toBeCloseTo(nodeRadius(-5));
    expect(nodeRadius(0.1)).toBeLessThan(nodeRadius(1));
    expect(nodeRadius(1)).toBeLessThan(nodeRadius(7));
    expect(nodeRadius(500)).toBe(nodeRadius(8));
    expect(nodeRadius(0)).toBeGreaterThan(0);
    // Big enough that the lightest holding is a visible circle, not a speck, once zoomed in.
    expect(nodeRadius(0)).toBeGreaterThanOrEqual(8);
    expect(nodeRadius(8)).toBeGreaterThanOrEqual(30);
  });
});

describe('rankedLinks', () => {
  it('lists every pair at or above the floor once, strongest first, never a null pair', () => {
    const ranked = rankedLinks(fund.corr, fund.n, 0.2);
    const pairs = Array.from({ length: ranked.count }, (_, k) => [ranked.a[k], ranked.b[k], ranked.v[k]]);

    expect(pairs.map(([a, b]) => [a, b])).toEqual([[3, 4], [0, 1], [2, 3], [1, 2], [0, 2], [1, 4], [0, 4], [2, 4]]);
    expect(pairs.map(([, , v]) => v)).toEqual([...pairs.map(([, , v]) => v)].sort((x, y) => y - x));
    expect(pairs.some(([a, b]) => a === 1 && b === 3)).toBe(false);     // the null pair
    expect(pairs.some(([a, b]) => a === 0 && b === 3)).toBe(false);     // 0.10, under the floor
  });
});

describe('linksAtLeast', () => {
  const ranked = rankedLinks(fund.corr, fund.n, 0.2);

  it('counts the links a threshold would draw', () => {
    expect(linksAtLeast(ranked, 0.7)).toBe(4);       // .95 .9 .8 .75
    expect(linksAtLeast(ranked, 0.9)).toBe(2);       // inclusive: .9 counts (float32-safe)
    expect(linksAtLeast(ranked, 0.96)).toBe(0);
    expect(linksAtLeast(ranked, 0.2)).toBe(ranked.count);
  });
});

describe('edgeBands', () => {
  const ranked = rankedLinks(fund.corr, fund.n, 0.2);

  it('splits the drawn links into contiguous strength bands covering exactly the ones above the threshold', () => {
    const bands = edgeBands(ranked, 0.7);

    expect(bands[0].start).toBe(0);
    expect(bands.at(-1).end).toBe(linksAtLeast(ranked, 0.7));
    bands.reduce((prev, band) => {
      expect(band.start).toBe(prev);
      expect(band.end).toBeGreaterThanOrEqual(band.start);
      return band.end;
    }, 0);
  });

  it('draws a stronger band darker and thicker than a weaker one', () => {
    const bands = edgeBands(ranked, 0.2);

    for (let i = 1; i < bands.length; i++) {
      expect(bands[i].alpha).toBeLessThan(bands[i - 1].alpha);
      expect(bands[i].width).toBeLessThan(bands[i - 1].width);
    }
  });
});

describe('neighboursOf', () => {
  it('are the holdings linked to one at or above the threshold, itself excluded, nulls never', () => {
    expect([...neighboursOf(fund.corr, fund.n, 3, 0.7)].sort()).toEqual([2, 4]);
    expect([...neighboursOf(fund.corr, fund.n, 1, 0.7)].sort()).toEqual([0, 2]);
    expect([...neighboursOf(fund.corr, fund.n, 3, 0.05)].sort()).toEqual([0, 2, 4]);   // not B: no pair
  });
});

describe('hitNode', () => {
  const xs = new Float32Array([100, 130, 500]);
  const ys = new Float32Array([100, 100, 500]);
  const radii = new Float32Array([20, 5, 5]);

  it('finds the node whose circle holds the point', () => {
    expect(hitNode({ xs, ys, radii }, 105, 100, 1)).toBe(0);
    expect(hitNode({ xs, ys, radii }, 500, 503, 1)).toBe(2);
  });

  it('is null in empty space', () => {
    expect(hitNode({ xs, ys, radii }, 300, 300, 1)).toBeNull();
  });

  it('gives a tiny node a hit area of a few pixels so it can be reached zoomed out', () => {
    // radius 5 world units at scale 0.25 is 1.25px; a 6px reach is 24 world units
    expect(hitNode({ xs, ys, radii }, 520, 500, 0.25)).toBe(2);
  });

  it('picks the nearer of two overlapping candidates', () => {
    expect(hitNode({ xs, ys, radii }, 126, 100, 1)).toBe(1);
  });
});

describe('labelShown', () => {
  it('shows a node\'s ticker once the node is big enough on screen for text beside it', () => {
    expect(labelShown(4, 1)).toBe(false);
    expect(labelShown(4, NODE_LABEL_MIN_PX / 4)).toBe(true);
    expect(labelShown(16, 1)).toBe(true);
  });
});

describe('networkLimits', () => {
  it('lets the whole graph fit at the bottom and a small node grow well past text size at the top', () => {
    const { min, max } = networkLimits({ scale: 0.4 });
    expect(min).toBe(0.4);
    expect(max).toBeGreaterThan(nodeRadius(0) > 0 ? NODE_LABEL_MIN_PX / nodeRadius(0) : 1);
  });
});

describe('layoutFullNetwork', () => {
  // Two tight groups of five, weakly tied to each other.
  const n = 10;
  const corr = new Float32Array(n * n);
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    corr[i * n + j] = i === j ? 1 : Math.floor(i / 5) === Math.floor(j / 5) ? 0.9 : 0.1;
  }
  const weights = Array(n).fill(2);

  it('returns a position for every node, inside the world with its margin', () => {
    const { xs, ys } = layoutFullNetwork({ corr, n, weights });

    expect(xs).toHaveLength(n);
    for (let i = 0; i < n; i++) {
      expect(xs[i]).toBeGreaterThanOrEqual(0);
      expect(xs[i]).toBeLessThanOrEqual(NETWORK_WORLD.w);
      expect(ys[i]).toBeGreaterThanOrEqual(0);
      expect(ys[i]).toBeLessThanOrEqual(NETWORK_WORLD.h);
    }
  });

  it('sits correlated holdings nearer each other than uncorrelated ones', () => {
    const { xs, ys } = layoutFullNetwork({ corr, n, weights });
    const dist = (i, j) => Math.hypot(xs[i] - xs[j], ys[i] - ys[j]);
    let within = 0, across = 0, w = 0, a = 0;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      if (Math.floor(i / 5) === Math.floor(j / 5)) { within += dist(i, j); w++; } else { across += dist(i, j); a++; }
    }
    expect(within / w).toBeLessThan(across / a);
  });

  it('still clusters a fund whose holdings are almost all a few hundredths of a percent', () => {
    // The pull between two holdings is scaled by their weight relative to the fund's
    // heaviest; over ~500 holdings that is near zero for the tail, and an unfloored
    // layout settles into a ring with no groups in it. Correlations here are noisy
    // and moderate, as real ones are: strong ones pull through the scaling anyway.
    const m = 500, groups = 11;
    const group = (i) => (i * 7919) % groups;
    let seed = 11;
    const noise = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const big = new Float32Array(m * m);
    for (let i = 0; i < m; i++) for (let j = i + 1; j < m; j++) {
      const same = group(i) === group(j);
      big[i * m + j] = big[j * m + i] = same ? 0.35 + noise() * 0.2 : 0.05 + noise() * 0.15;
    }
    for (let i = 0; i < m; i++) big[i * m + i] = 1;
    const tail = Array.from({ length: m }, (_, i) => 7.1 / Math.pow(1 + i, 0.9));

    const { xs, ys } = layoutFullNetwork({ corr: big, n: m, weights: tail });

    const dist = (i, j) => Math.hypot(xs[i] - xs[j], ys[i] - ys[j]);
    let within = 0, across = 0, w = 0, c = 0;
    for (let i = 0; i < m; i++) for (let j = i + 1; j < m; j++) {
      if (group(i) === group(j)) { within += dist(i, j); w++; } else { across += dist(i, j); c++; }
    }
    expect(within / w).toBeLessThan((across / c) * 0.6);
  }, 30000);

  it('lets strong links dominate: a tight core is much tighter than a loosely correlated group', () => {
    // Attraction is exponential in ρ, so a 0.92 pulls far harder than a 0.45 rather than
    // twice as hard. With the linear pull this ratio is 0.76; the exponential gives 0.64.
    const m = 30;
    const rho = (i, j) => {
      const a = Math.min(i, j), b = Math.max(i, j);
      if (b < 6) return 0.92;
      if (a >= 6 && b < 16) return 0.45;
      if (a < 6 && b >= 6 && b < 16) return 0.32;
      return 0.05;
    };
    const mixed = new Float32Array(m * m);
    for (let i = 0; i < m; i++) for (let j = 0; j < m; j++) mixed[i * m + j] = i === j ? 1 : rho(i, j);

    const { xs, ys } = layoutFullNetwork({ corr: mixed, n: m, weights: Array(m).fill(1) });

    const mean = (from, to) => {
      let sum = 0, count = 0;
      for (let i = from; i < to; i++) for (let j = i + 1; j < to; j++) { sum += Math.hypot(xs[i] - xs[j], ys[i] - ys[j]); count++; }
      return sum / count;
    };
    expect(mean(0, 6) / mean(6, 16)).toBeLessThan(0.7);
  });

  it('is the same every time it is asked, so a reload does not rearrange the graph', () => {
    const first = layoutFullNetwork({ corr, n, weights });
    const second = layoutFullNetwork({ corr, n, weights });
    expect(Array.from(second.xs)).toEqual(Array.from(first.xs));
  });

  it('does not treat a missing correlation as a pull', () => {
    const none = new Float32Array(n * n).fill(NaN);
    for (let i = 0; i < n; i++) none[i * n + i] = 1;
    const { xs } = layoutFullNetwork({ corr: none, n, weights });
    expect(xs.every(Number.isFinite)).toBe(true);
  });
});
