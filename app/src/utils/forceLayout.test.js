import { describe, it, expect } from 'vitest';
import { forceLayout, linearPull, exponentialPull } from './forceLayout';

describe('linearPull', () => {
  it('is the amount of ρ over 0.28, and nothing below it', () => {
    expect(linearPull(0.28)).toBe(0);
    expect(linearPull(0.1)).toBe(0);
    expect(linearPull(-0.5)).toBe(0);
    expect(linearPull(1)).toBeCloseTo(0.72);
    expect(linearPull(0.64)).toBeCloseTo(0.36);
  });
});

describe('exponentialPull', () => {
  const pull = exponentialPull({ steepness: 6, atOne: 3 });

  it('pulls nothing at or below the 0.28 floor, a missing pair included', () => {
    expect(pull(0.28)).toBe(0);
    expect(pull(0)).toBe(0);
    expect(pull(-0.9)).toBe(0);
  });

  it('is exactly `atOne` for a perfect correlation', () => {
    expect(pull(1)).toBeCloseTo(3);
  });

  it('grows with ρ, and faster the stronger the link', () => {
    const steps = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1].map(pull);
    for (let i = 1; i < steps.length; i++) expect(steps[i]).toBeGreaterThan(steps[i - 1]);
    const gains = steps.slice(1).map((v, i) => v - steps[i]);
    for (let i = 1; i < gains.length; i++) expect(gains[i]).toBeGreaterThan(gains[i - 1]);
  });

  it('makes a weak link little of what the linear pull made of it, and a strong one a lot more', () => {
    expect(pull(0.4)).toBeLessThan(linearPull(0.4) * 0.5);
    expect(pull(0.9)).toBeGreaterThan(linearPull(0.9) * 2);
  });
});

describe('forceLayout pull', () => {
  const n = 6;
  const weights = Array(n).fill(1);
  // Nodes 0-1 correlated strongly, 2-3 weakly, everything else not at all.
  const rho = (i, j) => {
    const [a, b] = i < j ? [i, j] : [j, i];
    if (a === 0 && b === 1) return 0.95;
    if (a === 2 && b === 3) return 0.4;
    return 0;
  };
  const gap = (pos, a, b) => Math.hypot(pos[a].x - pos[b].x, pos[a].y - pos[b].y);

  it('defaults to the linear pull, so the normal network does not move', () => {
    const plain = forceLayout({ weights, correlation: rho, aspect: 1 });
    const explicit = forceLayout({ weights, correlation: rho, aspect: 1, pull: linearPull });
    expect(explicit).toEqual(plain);
  });

  it('with an exponential pull, brings a strong pair far closer than a weak one', () => {
    const pos = forceLayout({
      weights, correlation: rho, aspect: 1, pull: exponentialPull({ steepness: 6, atOne: 3 }),
    });
    expect(gap(pos, 0, 1)).toBeLessThan(gap(pos, 2, 3) * 0.6);
  });
});
