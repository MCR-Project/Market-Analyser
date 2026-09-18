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
  const maxWeight = Math.max(...holdings.map(h => h[1]), 1e-6);
  const hasMatrix = !!corrMatrix && Object.keys(corrMatrix).length > 0;
  // Cache key includes the actual ticker set (not just etfId — holdings
  // can change under the same etfId, e.g. before/after live data arrives)
  // and whether the correlation matrix is live yet, so a layout computed
  // before the matrix loaded is never reused once real data is in.
  const cacheKey = etfId + ':' + ts.slice().sort().join(',') + ':' + (hasMatrix ? 'live' : 'pending') + ':' + aspect;
  if (layoutCache[cacheKey]) return layoutCache[cacheKey];

  const n = ts.length;
  // The simulation's working space: a fixed height, and the box's shape.
  // Positions are normalised to 0..1 at the end.
  const H = 440, W = H * aspect;
  // The pull toward the centre is what gives the settled graph its
  // outline — repulsion alone spreads it into a rough circle. Pulling
  // harder along the box's short axis settles it into the box's shape.
  const pullX = 0.01 * Math.max(1, 1 / aspect);
  const pullY = 0.01 * Math.max(1, aspect);

  // Seed positions evenly around an ellipse of the box's shape so the
  // simulation starts from a stable, non-overlapping arrangement rather
  // than a random jumble.
  const pos = ts.map((_, i) => ({
    x: W / 2 + Math.cos((2 * Math.PI * i) / n) * 120 * aspect,
    y: H / 2 + Math.sin((2 * Math.PI * i) / n) * 120,
  }));

  const k = 135;      // "ideal" spacing constant — bigger k pushes nodes further apart
  let temp = 90;       // max distance a node may move this iteration ("simulated annealing")

  // Fruchterman-Reingold-style force simulation: every pair of nodes
  // repels each other (like charged particles, so nodes never collide),
  // while correlated pairs also attract (so related stocks cluster).
  // Repeating this push/pull many times with a shrinking step size
  // ("cooling") lets the layout settle into a stable arrangement.
  for (let iter = 0; iter < 400; iter++) {
    const disp = ts.map(() => ({ x: 0, y: 0 })); // net displacement per node this iteration

    for (let i = 0; i < n; i++) {
      for (let jj = i + 1; jj < n; jj++) {
        let dx = pos[i].x - pos[jj].x, dy = pos[i].y - pos[jj].y;
        let d = Math.sqrt(dx * dx + dy * dy) || 0.01; // avoid div-by-zero for coincident nodes
        const ux = dx / d, uy = dy / d; // unit vector from j to i

        // Repulsion: inverse to distance, pushes every pair apart.
        const rep = (k * k) / d;
        disp[i].x += ux * rep; disp[i].y += uy * rep;
        disp[jj].x -= ux * rep; disp[jj].y -= uy * rep;

        // Attraction: proportional to distance, scaled by how correlated
        // the pair is (only correlations above 0.28 contribute, and the
        // amount over 0.28 is the strength). Uncorrelated/unknown pairs
        // (weight 0) get no extra pull, so they settle purely on repulsion.
        const w = Math.max(0, (corrMatrix?.[ts[i]]?.[ts[jj]] ?? 0) - 0.28);
        // Value factor: average of each holding's weight relative to the
        // fund's largest position (0..1). A pair involving a big holding
        // pulls harder even if its partner is small — mirroring how a
        // heavy stock like NVIDIA dominates the fund's actual behavior
        // far more than a light one like Micron.
        const valueFactor = ((weightOf[ts[i]] ?? 0) + (weightOf[ts[jj]] ?? 0)) / (2 * maxWeight);
        const att = ((d * d) / k) * w * valueFactor * 0.55;
        disp[i].x -= ux * att; disp[i].y -= uy * att;
        disp[jj].x += ux * att; disp[jj].y += uy * att;
      }
    }

    for (let i = 0; i < n; i++) {
      // Apply the net displacement, capped by the current "temperature"
      // so early iterations can move nodes far and later ones only nudge.
      let dl = Math.sqrt(disp[i].x * disp[i].x + disp[i].y * disp[i].y) || 0.01;
      pos[i].x += (disp[i].x / dl) * Math.min(dl, temp);
      pos[i].y += (disp[i].y / dl) * Math.min(dl, temp);
      // Gentle pull toward the center so the whole graph doesn't drift
      // off-canvas — stronger along the short axis (see pullX/pullY).
      pos[i].x += (W / 2 - pos[i].x) * pullX;
      pos[i].y += (H / 2 - pos[i].y) * pullY;
    }
    temp *= 0.975; // cool down — displacements shrink each iteration until the layout settles
  }

  // Normalize the settled positions to 0..1 on each axis, since the
  // simulation above has no notion of the box it will be drawn in;
  // computeLayout fits these into that box.
  const xs = pos.map(p => p.x), ys = pos.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const out = {};
  ts.forEach((t, i) => {
    out[t] = {
      x: (pos[i].x - minX) / (maxX - minX || 1),
      y: (pos[i].y - minY) / (maxY - minY || 1),
    };
  });

  layoutCache[cacheKey] = out;
  return out;
}
