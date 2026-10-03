import { describe, it, expect } from 'vitest';
import { readNumber, withParams } from './searchParams';

const params = (query) => new URLSearchParams(query);

describe('readNumber', () => {
  it('reads a number inside the range', () => {
    expect(readNumber(params('threshold=0.55'), 'threshold', 0.7, 0.2, 0.9)).toBe(0.55);
  });

  it('is the fallback when the key is absent', () => {
    expect(readNumber(params(''), 'threshold', 0.7, 0.2, 0.9)).toBe(0.7);
  });

  it('is the fallback for anything that is not a plain finite number', () => {
    for (const bad of ['abc', '', ' ', 'NaN', 'Infinity', '0.5x', '1e999']) {
      expect(readNumber(params(`threshold=${encodeURIComponent(bad)}`), 'threshold', 0.7, 0.2, 0.9)).toBe(0.7);
    }
  });

  it('clamps a number outside the range to its nearest end rather than dropping it', () => {
    expect(readNumber(params('threshold=0.05'), 'threshold', 0.7, 0.2, 0.9)).toBe(0.2);
    expect(readNumber(params('threshold=3'), 'threshold', 0.7, 0.2, 0.9)).toBe(0.9);
  });

  it('survives withParams: other keys travel with it, and a null value drops the key', () => {
    const next = withParams(params('matrixOrder=alpha&threshold=0.4'), { threshold: null });
    expect(next.get('matrixOrder')).toBe('alpha');
    expect(readNumber(next, 'threshold', 0.7, 0.2, 0.9)).toBe(0.7);
  });
});
