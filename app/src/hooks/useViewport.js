/**
 * useViewport — zoom and pan for a canvas (issue #173): wheel, drag, pinch and
 * the keyboard, over `utils/viewport.js`'s arithmetic.
 *
 * Takes the canvas element, the drawing's size in its own units (`content`), the
 * part of the canvas the drawing is shown in (`area`, `{x, y, w, h}` — the
 * matrix keeps margins for its labels) and `limitsFor(fit)`, the zoom limits for
 * a drawing whose whole-fit view is `fit`. Returns the current `view`, `zoomBy`
 * and `reset` for buttons, and `dragging` for the cursor.
 *
 * The view is the whole drawing until someone moves it, and is kept as the
 * drawing and the box change (a resize re-fits an untouched view, and clamps a
 * moved one). `resetKey` — the thing being drawn — drops a held view when it
 * changes, so a new fund is not shown through the last one's zoom.
 *
 * `onHover` is told where the pointer is while no button is down (and `null` when
 * it leaves or starts dragging), `onTap` where a press ended without moving more than
 * a few pixels — a drag is a pan, never a click. Both get `{ x, y, ax, ay, width,
 * height, view, area }`: the point in the canvas and in the area, the canvas's size,
 * and the view it was read against.
 *
 * Gestures change the view through a functional update on the latest state, so
 * several wheel events in one frame compound instead of each starting from the
 * view the last render saw. The handlers are native listeners (the wheel one
 * must be non-passive to stop the page scrolling) reading what they need from a
 * ref that is refreshed after every render.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fitView, zoomAt, panBy, clampView } from '../utils/viewport';

/** Pixels of the drawing that must stay in view, however far it is dragged. */
const KEEP = 80;
/** Pixels a press may move and still count as a tap. */
const TAP_SLOP = 4;
/** One zoom-button or key press. */
export const ZOOM_STEP = 1.4;

export function useViewport({ canvas, content, area, limitsFor, resetKey, pad = 0, onHover, onTap }) {
  const [held, setHeld] = useState({ key: resetKey, view: null });
  const [dragging, setDragging] = useState(false);

  const fit = useMemo(
    () => fitView(content, { w: area.w, h: area.h }, pad),
    [content, area.w, area.h, pad]
  );
  const limits = useMemo(() => limitsFor(fit), [limitsFor, fit]);

  const base = held.key === resetKey && held.view ? held.view : fit;
  const view = useMemo(
    () => clampView(
      { ...base, scale: Math.min(limits.max, Math.max(limits.min, base.scale)) },
      content, area, KEEP
    ),
    [base, limits, content, area]
  );

  const latest = useRef(null);
  useEffect(() => {
    latest.current = { fit, limits, content, area, resetKey, view, onHover, onTap };
  });

  const apply = useCallback((change) => {
    setHeld((prev) => {
      const l = latest.current;
      const start = prev.key === l.resetKey && prev.view ? prev.view : l.fit;
      return { key: l.resetKey, view: change(start, l) };
    });
  }, []);

  const zoomBy = useCallback(
    (factor) => apply((v, l) => zoomClamped(v, l, factor, l.area.w / 2, l.area.h / 2)),
    [apply]
  );
  const reset = useCallback(() => setHeld({ key: latest.current.resetKey, view: null }), []);

  useEffect(() => {
    if (!canvas) return undefined;

    const pointers = new Map();
    let press = null;      // the one-pointer press that may become a tap or a pan
    let pinch = null;      // the last distance and centre of a two-pointer pinch

    const local = (e) => {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const report = (p) => {
      const l = latest.current;
      return {
        x: p.x, y: p.y, ax: p.x - l.area.x, ay: p.y - l.area.y,
        width: canvas.clientWidth, height: canvas.clientHeight, view: l.view, area: l.area,
      };
    };

    const onWheel = (e) => {
      e.preventDefault();
      const p = local(e);
      const unit = e.deltaMode === 1 ? 0.05 : e.deltaMode === 2 ? 1 : 0.0016;
      const factor = Math.exp(-e.deltaY * unit);
      apply((v, l) => zoomClamped(v, l, factor, p.x - l.area.x, p.y - l.area.y));
    };

    const onDown = (e) => {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      canvas.setPointerCapture(e.pointerId);
      const p = local(e);
      pointers.set(e.pointerId, p);
      if (pointers.size === 1) {
        press = { moved: false, downX: p.x, downY: p.y, lastX: p.x, lastY: p.y };
      } else if (pointers.size === 2) {
        press = null;
        const [a, b] = [...pointers.values()];
        pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y) || 1, cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
      }
    };

    const onMove = (e) => {
      const p = local(e);
      if (!pointers.has(e.pointerId)) {
        latest.current.onHover?.(report(p));
        return;
      }
      pointers.set(e.pointerId, p);
      if (pointers.size === 2 && pinch) {
        const [a, b] = [...pointers.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
        const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
        const from = pinch;
        apply((v, l) => panBy(
          zoomClamped(v, l, dist / from.dist, from.cx - l.area.x, from.cy - l.area.y),
          cx - from.cx, cy - from.cy, l.content, l.area, KEEP
        ));
        pinch = { dist, cx, cy };
      } else if (press) {
        if (!press.moved && Math.hypot(p.x - press.downX, p.y - press.downY) > TAP_SLOP) {
          press.moved = true;
          setDragging(true);
          latest.current.onHover?.(null);
        }
        if (press.moved) {
          const dx = p.x - press.lastX, dy = p.y - press.lastY;
          apply((v, l) => panBy(v, dx, dy, l.content, l.area, KEEP));
        }
        press.lastX = p.x;
        press.lastY = p.y;
      }
    };

    const onUp = (e) => {
      const p = local(e);
      const ended = press;
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      if (e.type === 'pointerup' && ended && !ended.moved && pointers.size === 0) {
        latest.current.onTap?.(report(p));
      }
      if (pointers.size === 0) {
        press = null;
        setDragging(false);
      }
    };

    const onLeave = () => latest.current.onHover?.(null);

    const onKey = (e) => {
      const pan = (dx, dy) => apply((v, l) => panBy(v, dx, dy, l.content, l.area, KEEP));
      switch (e.key) {
        case '+': case '=': zoomBy(ZOOM_STEP); break;
        case '-': case '_': zoomBy(1 / ZOOM_STEP); break;
        case '0': reset(); break;
        case 'ArrowLeft': pan(60, 0); break;
        case 'ArrowRight': pan(-60, 0); break;
        case 'ArrowUp': pan(0, 60); break;
        case 'ArrowDown': pan(0, -60); break;
        default: return;
      }
      e.preventDefault();
    };

    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    canvas.addEventListener('pointerleave', onLeave);
    canvas.addEventListener('keydown', onKey);
    return () => {
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerup', onUp);
      canvas.removeEventListener('pointercancel', onUp);
      canvas.removeEventListener('pointerleave', onLeave);
      canvas.removeEventListener('keydown', onKey);
    };
  }, [canvas, apply, zoomBy, reset]);

  return { view, zoomBy, reset, dragging, atFit: view.scale <= limits.min * 1.001 };
}

function zoomClamped(view, l, factor, sx, sy) {
  return clampView(zoomAt(view, factor, sx, sy, l.limits), l.content, l.area, KEEP);
}
