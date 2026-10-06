/**
 * viewport — the zoom and pan arithmetic the Full view's two canvases share
 * (issue #173). Pure: a view and a gesture in, a view out. No DOM, no canvas.
 *
 * A **view** is `{ scale, x, y }` and maps the drawing's own ("world")
 * coordinates to the canvas's pixels: `screen = world * scale + (x, y)`. The
 * world is whatever the drawing is laid out in — the matrix is N × N cells of one
 * unit each, the network is a fixed 2400 × 1600 — so a gesture means the same
 * thing to both, and neither changes its layout to zoom: only this view moves.
 *
 * The rules a gesture obeys:
 *  - Zooming keeps the world point under the pointer where it is, so the picture
 *    grows round what is being looked at, not round a corner.
 *  - Scale stays between `limits.min` (the whole drawing fits) and `limits.max`.
 *  - Panning cannot lose the drawing: past `keep` pixels of it in view it stops. A
 *    drawing smaller than the box on an axis is centred on that axis, not dragged.
 */

/** The view that shows the whole `content` ({w, h}) in `box` ({w, h}), centred,
 *  with `pad` pixels round it. A box not yet measured (0 × 0) gives a tiny but
 *  valid scale rather than a division by zero. */
export function fitView(content, box, pad = 0) {
  const room = (side) => Math.max(1, side - 2 * pad);
  const scale = Math.min(room(box.w) / content.w, room(box.h) / content.h);
  return {
    scale,
    x: (box.w - content.w * scale) / 2,
    y: (box.h - content.h * scale) / 2,
  };
}

export function toWorld(view, sx, sy) {
  return { x: (sx - view.x) / view.scale, y: (sy - view.y) / view.scale };
}

export function toScreen(view, wx, wy) {
  return { x: wx * view.scale + view.x, y: wy * view.scale + view.y };
}

/** The part of the world a `box` shows under `view`. */
export function visibleRect(view, box) {
  const a = toWorld(view, 0, 0);
  const b = toWorld(view, box.w, box.h);
  return { x0: a.x, y0: a.y, x1: b.x, y1: b.y };
}

/** `view` zoomed by `factor` about the screen point (sx, sy), within `limits`
 *  ({min, max} scale). At a limit the view comes back unchanged. */
export function zoomAt(view, factor, sx, sy, limits) {
  const scale = Math.min(limits.max, Math.max(limits.min, view.scale * factor));
  if (scale === view.scale) return view;
  const ratio = scale / view.scale;
  return { scale, x: sx - (sx - view.x) * ratio, y: sy - (sy - view.y) * ratio };
}

/** `view` with the drawing kept inside the box: centred on an axis where it is
 *  smaller than the box, otherwise no further than `keep` pixels past either edge. */
export function clampView(view, content, box, keep) {
  const axis = (offset, contentSize, boxSize) => {
    const size = contentSize * view.scale;
    if (size <= boxSize) return (boxSize - size) / 2;
    return Math.min(keep, Math.max(boxSize - size - keep, offset));
  };
  const x = axis(view.x, content.w, box.w);
  const y = axis(view.y, content.h, box.h);
  return x === view.x && y === view.y ? view : { scale: view.scale, x, y };
}

/** `view` dragged by (dx, dy) pixels, clamped. */
export function panBy(view, dx, dy, content, box, keep) {
  return clampView({ scale: view.scale, x: view.x + dx, y: view.y + dy }, content, box, keep);
}
