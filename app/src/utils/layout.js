import { forceLayout } from './forceLayout';

const layoutCache = {};

/**
 * computeLayout — force-directed node positions for NetworkView.
 *
 * `corrMatrix` (from useLiveCorrelation) is used as the attraction force
 * between nodes — more correlated stocks are pulled closer together. No
 * mock correlation is used: pairs missing from the matrix simply get no
 * extra attraction (falls back to 0, i.e. repulsion-only spacing).
 *
 * Attraction is additionally scaled by each pair's fund weight (from
 * `holdings`), so heavier positions act like bigger "gravity wells" — a
 * highly-correlated pair involving a large holding (e.g. NVIDIA) pulls
 * together noticeably harder than the same correlation between two
 * small holdings (e.g. Micron).
 *
 * Positions come back in `width` × `height` — NetworkView's measured box
 * (issue #139), not a fixed canvas — at least `margin` from every edge;
 * the caller knows how big its nodes and labels get, so it says how much
 * room they need.
 *
 * The simulation runs in the box's shape, not a fixed one: a wide, short
 * box settles the graph into a wide, short arrangement, rather than a
 * 620×440 arrangement stretched 4× sideways, which flattened clusters
 * into bands. The shape is bucketed (quarter steps of width ÷ height)
 * and each bucket's result is cached as unit positions (0..1 on each
 * axis), so dragging a window edge refits cached positions instead of
 * re-running 400 iterations of an O(n²) simulation every frame.
 */
export function computeLayout(etfId, holdings, corrMatrix, width, height, margin) {
  const aspect = height > 0 ? Math.min(5, Math.max(0.75, Math.round((width / height) * 4) / 4)) : 1;
  const unit = simulate(etfId, holdings, corrMatrix, aspect);
  const out = {};
  for (const [t, p] of Object.entries(unit)) {
    out[t] = {
      x: margin + p.x * Math.max(0, width - 2 * margin),
      y: margin + p.y * Math.max(0, height - 2 * margin),
    };
  }
  return out;
}

/** The force simulation, cached per ETF, ticker set and box shape;
 *  positions are normalised to 0..1 so they can be fitted into any box
 *  of that shape. */
function simulate(etfId, holdings, corrMatrix, aspect) {
  const ts = holdings.map(h => h[0]);
  const weightOf = Object.fromEntries(holdings); // ticker -> weight%
  const hasMatrix = !!corrMatrix && Object.keys(corrMatrix).length > 0;
  // Cache key includes the actual ticker set (not just etfId — holdings
  // can change under the same etfId, e.g. before/after live data arrives)
  // and whether the correlation matrix is live yet, so a layout computed
  // before the matrix loaded is never reused once real data is in.
  const cacheKey = etfId + ':' + ts.slice().sort().join(',') + ':' + (hasMatrix ? 'live' : 'pending') + ':' + aspect;
  if (layoutCache[cacheKey]) return layoutCache[cacheKey];

  // The simulation itself is forceLayout.js's (shared with the Full view, issue
  // #173); this only says how a node pair's ρ is looked up in the nested matrix.
  const unit = forceLayout({
    weights: ts.map(t => weightOf[t] ?? 0),
    correlation: (i, j) => corrMatrix?.[ts[i]]?.[ts[j]] ?? null,
    aspect,
  });
  const out = {};
  ts.forEach((t, i) => { out[t] = unit[i]; });

  layoutCache[cacheKey] = out;
  return out;
}
