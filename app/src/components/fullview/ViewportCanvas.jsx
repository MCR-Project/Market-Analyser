/**
 * ViewportCanvas — the zoomable, pannable canvas both Full view drawings sit in
 * (issue #173).
 *
 * It owns what the two share and neither cares about: measuring its box
 * (`useElementSize`), sizing the canvas to that box at the screen's pixel ratio so
 * lines and text stay sharp, the viewport (`useViewport`: wheel, drag, pinch,
 * keyboard) and a paint whenever the view, the box, the colours or `draw` change.
 * A drawing supplies a `draw({ ctx, size, area, view, colors })` and the world it is
 * drawn in; because `draw` is a `useCallback` over everything the picture depends on
 * (selection, hover, threshold), a repaint is exactly "its identity changed".
 *
 * Always a square, as wide as the page (`Panel`), so the page scrolls to reach it rather
 * than the square shrinking to the height that is left.
 *
 * Sized by its container, never by what is drawn (the canvas is absolutely
 * positioned), for the reason `useElementSize` gives: drawing at the measured size
 * must not be able to grow the box it was measured from.
 *
 * The zoom buttons are real buttons for those who cannot wheel or pinch; the canvas
 * itself takes the keyboard (+, −, 0, arrows) when focused.
 *
 * `children` are drawn over the canvas (a tooltip), positioned by the caller from the
 * pointer position `onHover` reported.
 */
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useElementSize } from '../../hooks/useElementSize';
import { useViewport, ZOOM_STEP } from '../../hooks/useViewport';
import { Panel } from './Panel';

export function ViewportCanvas({
  content, areaFor, limitsFor, pad = 0, resetKey, colors, draw, onHover, onTap,
  cursor, label, children,
}) {
  const [boxRef, size] = useElementSize();
  // The element is held twice: in state, so the viewport hook re-attaches its
  // listeners when it mounts, and in a ref, which the paint below may write to.
  const [canvas, setCanvas] = useState(null);
  const canvasRef = useRef(null);
  const attachCanvas = useCallback((element) => {
    canvasRef.current = element;
    setCanvas(element);
  }, []);
  const area = useMemo(() => areaFor(size), [areaFor, size]);

  const { view, zoomBy, reset, dragging, atFit } = useViewport({
    canvas, content, area, limitsFor, resetKey, pad, onHover, onTap,
  });

  useLayoutEffect(() => {
    const target = canvasRef.current;
    if (!target || !colors || size.width === 0 || size.height === 0) return;
    const ratio = window.devicePixelRatio || 1;
    const width = Math.round(size.width * ratio);
    const height = Math.round(size.height * ratio);
    // Assigning a canvas's size clears it and reallocates its buffer, so only when it changed.
    if (target.width !== width) target.width = width;
    if (target.height !== height) target.height = height;
    const ctx = target.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, size.width, size.height);
    draw({ ctx, size, area, view, colors });
  }, [canvas, size, area, view, colors, draw]);

  const zoomIn = useCallback(() => zoomBy(ZOOM_STEP), [zoomBy]);
  const zoomOut = useCallback(() => zoomBy(1 / ZOOM_STEP), [zoomBy]);

  return (
    <Panel ref={boxRef}>
      <canvas
        ref={attachCanvas}
        tabIndex={0}
        role="img"
        aria-label={label}
        className="absolute inset-0 block w-full h-full touch-none outline-none focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--accent)]"
        style={{ cursor: dragging ? 'grabbing' : (cursor ?? 'grab') }}
      />
      <div className="absolute top-2 right-2 flex gap-1">
        <ZoomButton onClick={zoomIn} title="Zoom in (+)">+</ZoomButton>
        <ZoomButton onClick={zoomOut} title="Zoom out (−)">−</ZoomButton>
        <ZoomButton onClick={reset} disabled={atFit} title="Show everything (0)">Fit</ZoomButton>
      </div>
      {children}
    </Panel>
  );
}

function ZoomButton({ children, ...props }) {
  return (
    <button
      type="button"
      {...props}
      className="min-w-8 h-8 px-2 grid place-items-center font-[var(--font-mono)] text-sm font-semibold text-[var(--fg-1)] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-sm)] cursor-pointer shadow-[var(--shadow-xs)] transition-colors duration-150 hover:bg-[var(--bg-2)] disabled:opacity-40 disabled:cursor-default"
    >
      {children}
    </button>
  );
}
