/**
 * forceLayout — the force simulation both network graphs settle their nodes
 * with: the normal one (`layout.js`, ~50 nodes) and the Full view's (issue #173,
 * ~500, in a worker). Pure: weights and a correlation lookup in, unit positions
 * out. It lived inside `layout.js`; it moved here unchanged so the Full view does
 * not carry a second copy of constants that were tuned by eye, and
 * `layout.test.js` pins that the normal graph still lands where it always has.
 *
 * Every pair of nodes repels (so nodes never collide) while correlated pairs also
 * attract (so related stocks cluster), repeated with a shrinking step size
 * ("cooling") until the arrangement settles — Fruchterman–Reingold.
 *
 * `weights` is each node's fund weight, which scales the attraction: a pair
 * involving a heavy holding pulls harder than the same ρ between two light ones,
 * mirroring how a big position dominates the fund. `correlation(i, j)` is the ρ
 * between nodes `i` and `j` or null when there is none; only the amount over 0.28
 * pulls, and null pulls nothing (no mock correlation is invented — an unknown pair
 * settles on repulsion alone).
 *
 * The simulation runs in the shape of the box it will be drawn in (`aspect`, width ÷
 * height) rather than a fixed one, so a wide short box settles into a wide short
 * arrangement instead of a square one stretched sideways, which flattened clusters
 * into bands (issue #139). Positions come back normalised to 0..1 on each axis;
 * the caller fits them into its box.
 */

export const DEFAULT_ITERATIONS = 400;

/**
 * @param {object} args
 * @param {number[]} args.weights                          fund weight of each node
 * @param {(i: number, j: number) => number | null} args.correlation
 * @param {number} args.aspect                             box width ÷ height
 * @param {number} [args.iterations]
 * @returns {Array<{x: number, y: number}>}               unit positions, in node order
 */
export function forceLayout({ weights, correlation, aspect, iterations = DEFAULT_ITERATIONS }) {
  const n = weights.length;
  const maxWeight = Math.max(...weights, 1e-6);

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
  const pos = weights.map((_, i) => ({
    x: W / 2 + Math.cos((2 * Math.PI * i) / n) * 120 * aspect,
    y: H / 2 + Math.sin((2 * Math.PI * i) / n) * 120,
  }));

  const k = 135;      // "ideal" spacing constant — bigger k pushes nodes further apart
  let temp = 90;       // max distance a node may move this iteration ("simulated annealing")

  for (let iter = 0; iter < iterations; iter++) {
    const disp = weights.map(() => ({ x: 0, y: 0 })); // net displacement per node this iteration

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
        const w = Math.max(0, (correlation(i, jj) ?? 0) - 0.28);
        // Value factor: average of each holding's weight relative to the
        // fund's largest position (0..1). A pair involving a big holding
        // pulls harder even if its partner is small — mirroring how a
        // heavy stock like NVIDIA dominates the fund's actual behavior
        // far more than a light one like Micron.
        const valueFactor = ((weights[i] ?? 0) + (weights[jj] ?? 0)) / (2 * maxWeight);
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
  // simulation above has no notion of the box it will be drawn in.
  const xs = pos.map(p => p.x), ys = pos.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  return pos.map(p => ({
    x: (p.x - minX) / (maxX - minX || 1),
    y: (p.y - minY) / (maxY - minY || 1),
  }));
}
