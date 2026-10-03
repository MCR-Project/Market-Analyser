/**
 * fullMatrix — what the Full view's matrix canvas decides, apart from drawing it
 * (issue #173). Pure: the decoded fund and a viewport in, arrangement, pixels,
 * hit-tests and label thresholds out; `components/fullview/FullMatrix.jsx` only
 * paints what this returns.
 *
 * **The matrix is a bitmap, not 250,000 shapes.** Each cell is one pixel of an
 * N × N image (`cellPixels`) that is built once, and zooming is the canvas
 * scaling that image with smoothing off, so a cell is a crisp square at any zoom
 * and a pan or zoom costs one `drawImage`, not a loop over cells. The viewport's
 * world is N × N units, one per cell, so `scale` *is* the cell's size in pixels
 * (see `viewport.js`).
 *
 * **Order** is `matrixOrder.js`'s, unchanged — clusters as labelled blocks on the
 * diagonal by default, or A–Z, or by weight — asked for every holding rather than
 * a top-N, since the Full view shows the whole fund. Colour keeps meaning ρ and
 * nothing else (as in the normal matrix): the ramp is `correlation.js`'s
 * `cellColor` sampled at each percentage, and a pair with no correlation is a flat
 * neutral, never a point on the ramp.
 *
 * **Labels appear when they can be read.** A row or column label needs a cell about
 * `LABEL_MIN_CELL_PX` tall to sit beside; a value inside a cell needs about
 * `VALUE_MIN_CELL_PX` to fit "−0.12". Below those the canvas draws the colours
 * alone, so zooming out never paints 500 overlapping words.
 */

import { orderMatrix } from './matrixOrder';
import { toWorld } from './viewport';

export const LABEL_MIN_CELL_PX = 12;
export const VALUE_MIN_CELL_PX = 34;
export const MATRIX_MAX_CELL_PX = 80;

/**
 * The drawing order for the whole fund: `order[r]` is the index (into the decoded
 * fund) of the holding drawn in row and column `r`; `sections` and `clusterOf` are
 * `orderMatrix`'s.
 */
export function arrange(fund, order, within) {
  const { tickers, sections, clusterOf } = orderMatrix({
    holdings: fund.holdings,
    clusters: fund.clusters,
    averages: fund.averages,
    n: fund.n,
    order,
    within,
  });
  return { order: tickers.map((t) => fund.indexOf.get(t)), sections, clusterOf };
}

/** The colour-ramp step for a correlation: its whole percentage, from 0 to 100.
 *  A negative ρ is the lightest step, as in `cellColor`. */
export function rampIndex(v) {
  return Math.min(100, Math.max(0, Math.round(v * 100)));
}

/**
 * RGBA bytes for the N × N bitmap, in drawing order. `palette` is
 * `{ ramp: [[r,g,b] × 101], none: [r,g,b], diagonal: [r,g,b] }` — resolved from the
 * page's theme by the component, since a canvas cannot read CSS variables.
 */
export function cellPixels(order, corr, n, palette) {
  const pixels = new Uint8ClampedArray(n * n * 4);
  for (let r = 0; r < n; r++) {
    const i = order[r];
    for (let c = 0; c < n; c++) {
      const j = order[c];
      const v = corr[i * n + j];
      const rgb = i === j ? palette.diagonal : Number.isNaN(v) ? palette.none : palette.ramp[rampIndex(v)];
      const at = (r * n + c) * 4;
      pixels[at] = rgb[0];
      pixels[at + 1] = rgb[1];
      pixels[at + 2] = rgb[2];
      pixels[at + 3] = 255;
    }
  }
  return pixels;
}

/** The cell under (ax, ay) — a point in the matrix area, the canvas less its label
 *  margins — or null off the matrix. `row` and `col` are drawing positions. */
export function cellAt(view, ax, ay, n) {
  const world = toWorld(view, ax, ay);
  const row = Math.floor(world.y);
  const col = Math.floor(world.x);
  return row >= 0 && row < n && col >= 0 && col < n ? { row, col } : null;
}

/** What to write at a cell size (px): row/column labels, and ρ inside each cell,
 *  each with the font size to use. */
export function labelPlan(cellPx) {
  const labels = cellPx >= LABEL_MIN_CELL_PX;
  const values = cellPx >= VALUE_MIN_CELL_PX;
  return {
    labels,
    values,
    labelPx: labels ? Math.min(12, Math.max(9, Math.floor(cellPx * 0.75))) : 0,
    valuePx: values ? Math.min(13, Math.max(10, Math.floor(cellPx * 0.32))) : 0,
  };
}

/** The cells (half-open row and column ranges) the area shows, clipped to the matrix. */
export function visibleCells(view, area, n) {
  const x0 = toWorld(view, 0, 0);
  const x1 = toWorld(view, area.w, area.h);
  const c0 = Math.max(0, Math.floor(x0.x));
  const r0 = Math.max(0, Math.floor(x0.y));
  return {
    r0, c0,
    r1: Math.max(r0, Math.min(n, Math.ceil(x1.y))),
    c1: Math.max(c0, Math.min(n, Math.ceil(x1.x))),
  };
}

/** The cluster sections as squares on the diagonal. "Others" and "No history" are
 *  bands, not blocks — nothing binds their members to one another — so they get no
 *  outline (the same rule the normal matrix follows). */
export function clusterBlocks(sections) {
  return (sections ?? [])
    .filter((s) => s.kind === 'cluster')
    .map(({ key, label, start, count }) => ({ key, label, start, count }));
}

/** Zoom limits for a matrix whose whole-fit view has `fit.scale`. */
export function matrixLimits(fit) {
  return { min: fit.scale, max: Math.max(MATRIX_MAX_CELL_PX, fit.scale) };
}
