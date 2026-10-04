/**
 * fullNetwork — what the Full view's network canvas decides, apart from drawing
 * it (issue #173). Pure: the decoded fund in; links, bands, neighbours, hit-tests
 * and label thresholds out. `components/fullview/FullNetwork.jsx` paints it, and
 * `fullNetworkLayout.js` (run once, in a worker) places the nodes.
 *
 * **The Link Threshold moves no node and asks for nothing.** Positions come from
 * the layout, which reads the matrix and nothing the slider owns; the threshold
 * only chooses which links are drawn. So the links worth ever drawing (ρ ≥
 * `THRESHOLD_MIN`) are collected once and sorted strongest first (`rankedLinks`),
 * and "the links at 0.7" is then a *prefix* of that list: a count is a binary
 * search (`linksAtLeast`), and the strength bands are contiguous slices of it
 * (`edgeBands`), so dragging the slider costs a search and a redraw — never a pass
 * over 125,000 pairs, and never a request.
 *
 * Correlations are held as float32 (`fullView.js`), so a stored 0.9 reads back as
 * 0.8999999762; a link sitting exactly on the threshold would otherwise drop out.
 * `EPS` is far smaller than the 0.01 the slider moves in and the 0.01 the data is
 * rounded to, so it changes no link that is not on the line.
 *
 * Nothing here knows about drawing a node's logo: 500 of them would be 500 image
 * requests, and a node's size and place already say what the normal view's icon
 * does not need to.
 */

/** The fixed world the graph is laid out in; the viewport fits it to the canvas. */
export const NETWORK_WORLD = { w: 2400, h: 1600 };
/** Room at the world's edge for the heaviest node and its label. */
export const NETWORK_MARGIN = 60;

export const DEFAULT_THRESHOLD = 0.7;
export const THRESHOLD_MIN = 0.2;
export const THRESHOLD_MAX = 0.95;
export const THRESHOLD_STEP = 0.01;

/** A node's ticker is written once the node is this many pixels across its radius. */
export const NODE_LABEL_MIN_PX = 8;
/** Reach, in pixels, a node has for a pointer however small it is drawn. */
export const NODE_HIT_MIN_PX = 6;
export const NETWORK_MAX_SCALE = 12;

const EPS = 1e-4;
// Node size by weight: the normal network's exponential (utils NetworkView), so a
// 7% holding is dramatically bigger than a 2% one, in world units here.
const MIN_R = 8, MAX_R = 34, REF_WEIGHT = 8, GROWTH = 4;

export function nodeRadius(weightPct) {
  const t = Math.min(1, Math.max(0, weightPct) / REF_WEIGHT);
  const curve = (Math.exp(GROWTH * t) - 1) / (Math.exp(GROWTH) - 1);
  return MIN_R + curve * (MAX_R - MIN_R);
}

/**
 * Every pair of holdings correlated at `floor` or more, strongest first, as parallel
 * arrays: holdings `a[k] < b[k]` with correlation `v[k]`. A pair with no
 * correlation (NaN) is never a link.
 */
export function rankedLinks(corr, n, floor) {
  const found = [];
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const v = corr[i * n + j];
      if (v >= floor - EPS) found.push(i * n + j);
    }
  }
  found.sort((x, y) => corr[y] - corr[x] || x - y);
  const a = new Uint16Array(found.length);
  const b = new Uint16Array(found.length);
  const v = new Float32Array(found.length);
  found.forEach((key, k) => {
    a[k] = Math.floor(key / n);
    b[k] = key % n;
    v[k] = corr[key];
  });
  return { a, b, v, count: found.length };
}

/** How many of `ranked`'s links a threshold draws: those with ρ ≥ it. */
export function linksAtLeast(ranked, threshold) {
  let lo = 0, hi = ranked.count;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (ranked.v[mid] >= threshold - EPS) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

const BAND_COUNT = 4;

/**
 * The drawn links as up to four contiguous bands of `ranked`, strongest first, each
 * with the stroke it is drawn in (`alpha`, `width` in pixels): a stronger link is
 * darker and thicker, as in the normal network. One path per band, not per link.
 * A band with no links is left out.
 */
export function edgeBands(ranked, threshold) {
  const drawn = linksAtLeast(ranked, threshold);
  const bands = [];
  let start = 0;
  for (let q = 1; q <= BAND_COUNT; q++) {
    // The weakest ρ a link in this band may have: a quarter-step down the range
    // from 1 to the threshold. The last band reaches the threshold itself.
    const floor = q === BAND_COUNT ? threshold : 1 - ((1 - threshold) * q) / BAND_COUNT;
    let end = start;
    while (end < drawn && ranked.v[end] >= floor - EPS) end++;
    if (end > start) {
      bands.push({ start, end, alpha: 0.55 - (q - 1) * 0.14, width: 2.2 - (q - 1) * 0.5 });
    }
    start = end;
  }
  return bands;
}

/** The holdings linked to holding `i` at or above `threshold`, itself excluded. */
export function neighboursOf(corr, n, i, threshold) {
  const found = new Set();
  for (let j = 0; j < n; j++) {
    if (j !== i && corr[i * n + j] >= threshold - EPS) found.add(j);
  }
  return found;
}

/**
 * The node under a point (world coordinates), or null. `nodes` is
 * `{ xs, ys, radii }`. A node answers within its own radius, or within
 * `NODE_HIT_MIN_PX` on screen if that is larger, so a small node is still reachable
 * zoomed out. The nearest centre wins where reaches overlap.
 */
export function hitNode(nodes, wx, wy, scale) {
  const reach = NODE_HIT_MIN_PX / scale;
  let best = null;
  let bestDist = Infinity;
  for (let i = 0; i < nodes.xs.length; i++) {
    const d = Math.hypot(nodes.xs[i] - wx, nodes.ys[i] - wy);
    if (d <= Math.max(nodes.radii[i], reach) && d < bestDist) {
      best = i;
      bestDist = d;
    }
  }
  return best;
}

/** Whether a node of world radius `r` is big enough on screen to carry its ticker. */
export function labelShown(r, scale) {
  return r * scale >= NODE_LABEL_MIN_PX;
}

/** Zoom limits for a graph whose whole-fit view has `fit.scale`. */
export function networkLimits(fit) {
  return { min: fit.scale, max: Math.max(NETWORK_MAX_SCALE, fit.scale) };
}
