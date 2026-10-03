/**
 * fullNetworkLayout — where the Full view's network puts its nodes (issue #173).
 *
 * The same force simulation as the normal graph (`forceLayout.js`), over the
 * decoded fund's correlation matrix and fitted into the fixed world the viewport
 * zooms (`NETWORK_WORLD`). ~125,000 pairs × 400 iterations is most of a second,
 * which on the page's own thread is a frozen tab, so `workers/fullNetworkLayout.worker.js`
 * runs it and `hooks/useFullNetworkLayout.js` falls back to calling it directly
 * where workers are unavailable. Deterministic — there is no randomness in it — so
 * opening the same result twice draws the same graph.
 *
 * **The weight that scales a pull is floored.** The shared simulation pulls a pair
 * together in proportion to its two holdings' weights relative to the fund's
 * heaviest, which suits ~46 holdings and is nearly zero for the ~450 under 0.2% of a
 * fund this size: with real, moderate correlations their pull is lost against the
 * repulsion and the graph settles into a ring with no groups in it. So the weight
 * handed to the simulation is `LAYOUT_WEIGHT_FLOOR` of the heaviest holding's plus the
 * rest by the holding's own: a heavy holding still pulls harder than a light one,
 * but no holding is nothing. It changes where nodes sit and nothing about what a link
 * or a node's size means.
 *
 * The layout is computed once per result and never from the Link Threshold: it
 * reads every ρ the matrix has, so moving the slider moves no node.
 */

import { forceLayout, exponentialPull } from './forceLayout';
import { NETWORK_WORLD, NETWORK_MARGIN } from './fullNetwork';

/**
 * **Attraction is exponential in ρ.** The normal network pulls in proportion to the
 * amount of ρ over 0.28; over ~500 holdings that lets thousands of middling links
 * add up to as much as a few strong ones, and the strong ones are what a reader wants
 * to see grouped. So a link's pull bends upward: `PULL_STEEPNESS` says how fast, and
 * `PULL_AT_ONE` how hard a perfect correlation pulls (the linear pull's own top is
 * 0.72). Only attraction changes — repulsion, the one that keeps nodes apart, is the
 * simulation's own and untouched.
 */
export const PULL_STEEPNESS = 6;
export const PULL_AT_ONE = 3;
const pull = exponentialPull({ steepness: PULL_STEEPNESS, atOne: PULL_AT_ONE });

/** Share of the heaviest holding's weight every holding is given for the layout. */
export const LAYOUT_WEIGHT_FLOOR = 0.35;

/**
 * @param {{ corr: Float32Array, n: number, weights: number[] }} args
 * @returns {{ xs: Float32Array, ys: Float32Array }} world coordinates, in node order
 */
export function layoutFullNetwork({ corr, n, weights }) {
  const heaviest = Math.max(...weights, 1e-6);
  const unit = forceLayout({
    weights: weights.map((w) => LAYOUT_WEIGHT_FLOOR * heaviest + (1 - LAYOUT_WEIGHT_FLOOR) * w),
    correlation: (i, j) => {
      const v = corr[i * n + j];
      return Number.isNaN(v) ? null : v;
    },
    aspect: NETWORK_WORLD.w / NETWORK_WORLD.h,
    pull,
  });
  const xs = new Float32Array(n);
  const ys = new Float32Array(n);
  unit.forEach((p, i) => {
    xs[i] = NETWORK_MARGIN + p.x * (NETWORK_WORLD.w - 2 * NETWORK_MARGIN);
    ys[i] = NETWORK_MARGIN + p.y * (NETWORK_WORLD.h - 2 * NETWORK_MARGIN);
  });
  return { xs, ys };
}
