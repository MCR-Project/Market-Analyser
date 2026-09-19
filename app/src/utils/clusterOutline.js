/**
 * clusterOutline — the soft outline NetworkView draws around one cluster's
 * nodes (issue #144). Pure geometry: circles in, a closed polygon out.
 *
 * The outline is the convex hull of a ring of points sampled around every
 * node, `pad` pixels outside its circle, plus the corners of the ticker
 * label under it (a node's label sits below its circle, so an outline hugging
 * only the circles would cut the label in half). Sampling the circles rather
 * than hulling the centres is what makes the padding correct for nodes of
 * very different sizes — a 60px-radius node and a 10px one in one cluster
 * both end up `pad` pixels inside the line, not the big one poking through.
 * The hull of two circles comes out capsule-shaped, of three or more a
 * rounded polygon; with 16 samples a circle reads as round at any size a
 * node can be, and a round `stroke-linejoin` takes care of the corners.
 *
 * **What it does and does not promise.** Every member's circle and label
 * are inside the outline. It does not promise that no *other* node is: the
 * layout is a force simulation that attracts correlated pairs but knows
 * nothing about clusters (issue #144 leaves that out of scope on purpose),
 * so a cluster whose members sit apart can enclose a stranger between
 * them. A convex outline is the honest, cheap answer to "these are the
 * ones"; it is not a claim that the region is exclusively theirs.
 *
 * **Bounds.** The layout keeps every node and its label inside the drawing
 * box, but not the padding around them: a heavy node at the box's edge has
 * `pad` more pixels of outline than the box has room for, and the SVG would
 * clip the dashed line. Passing `bounds` clamps the outline's points into
 * the box. Clamping can only pull a point *toward* the members, never past
 * them (each circle and label was already inside the box), so every member
 * stays enclosed; the outline just loses the padding it had no room for.
 */

const SAMPLES = 16;

/** Cross product of OA and OB: positive when O→A→B turns counter-clockwise. */
const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

/** Andrew's monotone chain: the convex hull of `points`, counter-clockwise. */
function convexHull(points) {
  const sorted = [...points].sort((p, q) => p[0] - q[0] || p[1] - q[1]);
  const unique = sorted.filter((p, i) => i === 0 || p[0] !== sorted[i - 1][0] || p[1] !== sorted[i - 1][1]);
  if (unique.length < 3) return unique;

  const half = (seq) => {
    const chain = [];
    for (const p of seq) {
      while (chain.length >= 2 && cross(chain[chain.length - 2], chain[chain.length - 1], p) <= 0) chain.pop();
      chain.push(p);
    }
    chain.pop();
    return chain;
  };
  return [...half(unique), ...half([...unique].reverse())];
}

/**
 * @param {Array<{x: number, y: number, r: number, labelHalfWidth?: number, labelDepth?: number}>} nodes
 *   circles in drawing pixels. `labelHalfWidth` and `labelDepth` describe the
 *   ticker label under a node — half its width, and how far below the node's
 *   centre its bottom edge is — and are optional.
 * @param {number} pad  pixels of clearance around each circle and label
 * @param {{minX: number, minY: number, maxX: number, maxY: number}} [bounds]
 *   the drawing box; the outline is clamped inside it. Omitted, it is not.
 * @returns {null | { points: number[][], path: string, top: number, bottom: number, centerX: number }}
 *   `null` for fewer than two nodes: a cluster is two or more. Otherwise the
 *   hull's points, an SVG path for it, and its top edge, bottom edge and
 *   horizontal centre (where the caller hangs its label).
 */
export function clusterOutline(nodes, pad, bounds) {
  if (nodes.length < 2) return null;

  const points = [];
  for (const n of nodes) {
    for (let k = 0; k < SAMPLES; k++) {
      const angle = (2 * Math.PI * k) / SAMPLES;
      points.push([n.x + Math.cos(angle) * (n.r + pad), n.y + Math.sin(angle) * (n.r + pad)]);
    }
    if (n.labelHalfWidth) {
      const y = n.y + n.labelDepth + pad;
      points.push([n.x - n.labelHalfWidth - pad, y], [n.x + n.labelHalfWidth + pad, y]);
    }
  }

  const inBox = bounds
    ? points.map(([x, y]) => [Math.min(bounds.maxX, Math.max(bounds.minX, x)), Math.min(bounds.maxY, Math.max(bounds.minY, y))])
    : points;
  const hull = convexHull(inBox);
  const xs = hull.map(p => p[0]), ys = hull.map(p => p[1]);
  const fmt = (p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`;

  return {
    points: hull,
    path: `M${fmt(hull[0])}${hull.slice(1).map(p => `L${fmt(p)}`).join('')}Z`,
    top: Math.min(...ys),
    bottom: Math.max(...ys),
    centerX: (Math.min(...xs) + Math.max(...xs)) / 2,
  };
}
