import { describe, it, expect } from 'vitest';
import { fitView, zoomAt, panBy, clampView, toWorld, toScreen, visibleRect } from './viewport';

const content = { w: 1000, h: 500 };
const box = { w: 800, h: 600 };

describe('fitView', () => {
  it('scales the content to fit the box, centred, with the padding left round it', () => {
    const view = fitView(content, box, 20);
    expect(view.scale).toBeCloseTo((800 - 40) / 1000);
    // centred on the axis with room to spare (y), flush to the padding on the tight one (x)
    expect(view.x).toBeCloseTo(20);
    expect(view.y).toBeCloseTo((600 - 500 * view.scale) / 2);
  });

  it('is a scale of 1 for a box exactly the content size', () => {
    expect(fitView({ w: 300, h: 300 }, { w: 300, h: 300 })).toEqual({ scale: 1, x: 0, y: 0 });
  });

  it('does not divide by zero for an unmeasured box', () => {
    const view = fitView(content, { w: 0, h: 0 });
    expect(Number.isFinite(view.scale)).toBe(true);
    expect(view.scale).toBeGreaterThan(0);
  });
});

describe('toWorld / toScreen', () => {
  it('are inverses', () => {
    const view = { scale: 2.5, x: -120, y: 40 };
    const w = toWorld(view, 333, 77);
    const s = toScreen(view, w.x, w.y);
    expect(s.x).toBeCloseTo(333);
    expect(s.y).toBeCloseTo(77);
  });
});

describe('zoomAt', () => {
  const limits = { min: 0.5, max: 8 };

  it('keeps the world point under the pointer where it was', () => {
    const view = { scale: 1, x: 0, y: 0 };
    const before = toWorld(view, 300, 200);
    const next = zoomAt(view, 2, 300, 200, limits);
    const after = toWorld(next, 300, 200);
    expect(next.scale).toBe(2);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
  });

  it('never goes past either limit, and then holds the point steady at the limit', () => {
    const out = zoomAt({ scale: 7, x: 10, y: 10 }, 5, 100, 100, limits);
    expect(out.scale).toBe(8);
    const same = zoomAt(out, 5, 100, 100, limits);
    expect(same).toEqual(out);
    expect(zoomAt({ scale: 0.6, x: 0, y: 0 }, 0.1, 0, 0, limits).scale).toBe(0.5);
  });
});

describe('clampView', () => {
  it('centres content that is smaller than the box on that axis', () => {
    const view = clampView({ scale: 0.5, x: 700, y: -300 }, content, box, 80);
    expect(view.x).toBeCloseTo((800 - 500) / 2);
    expect(view.y).toBeCloseTo((600 - 250) / 2);
  });

  it('lets oversized content be dragged only until `keep` pixels of it are left in view', () => {
    const big = { scale: 2, x: 0, y: 0 };               // content is 2000 x 1000 on screen
    expect(clampView({ ...big, x: 5000 }, content, box, 80).x).toBe(80);
    expect(clampView({ ...big, x: -5000 }, content, box, 80).x).toBe(800 - 2000 - 80);
    expect(clampView({ ...big, y: 5000 }, content, box, 80).y).toBe(80);
    expect(clampView({ ...big, y: -5000 }, content, box, 80).y).toBe(600 - 1000 - 80);
  });

  it('leaves a view already inside alone', () => {
    const view = { scale: 2, x: -300, y: -100 };
    expect(clampView(view, content, box, 80)).toEqual(view);
  });
});

describe('panBy', () => {
  it('moves the view by the drag and clamps the result', () => {
    const view = { scale: 2, x: 0, y: 0 };
    expect(panBy(view, -50, -20, content, box, 80)).toEqual({ scale: 2, x: -50, y: -20 });
    expect(panBy(view, 9999, 0, content, box, 80).x).toBe(80);
  });
});

describe('visibleRect', () => {
  it('is the part of the world the box shows', () => {
    const rect = visibleRect({ scale: 2, x: -100, y: -40 }, { w: 800, h: 600 });
    expect(rect).toEqual({ x0: 50, y0: 20, x1: 450, y1: 320 });
  });
});
