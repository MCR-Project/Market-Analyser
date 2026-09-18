/**
 * useElementSize — the rendered content-box size of one element, kept
 * current by a ResizeObserver (issue #139).
 *
 * For the drawings that lay themselves out in pixels rather than
 * stretching: NetworkView places nodes in its measured box, and
 * MatrixView sizes its cells to fit the box it has. Both used to assume
 * a fixed box, which left a small drawing floating in a large panel on
 * a wide screen.
 *
 * `{ width: 0, height: 0 }` until the first measurement, so a caller
 * can tell "not measured yet" from a real size and hold off drawing
 * rather than laying out into a box that does not exist.
 *
 * The element must size itself from its container, not from what is
 * drawn inside it (e.g. `flex-1 min-h-0`, or absolutely positioned
 * content) — otherwise drawing at the measured size grows the element,
 * which is measured again, and the two chase each other.
 *
 * The returned ref is a callback ref, so a view that renders a loading
 * state first and the measured box later starts observing when the box
 * actually mounts, not only on the view's first render.
 */
import { useLayoutEffect, useState } from 'react';

export function useElementSize() {
  const [el, ref] = useState(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useLayoutEffect(() => {
    if (!el) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.round(entry.contentRect.width);
      const height = Math.round(entry.contentRect.height);
      // Same object back when nothing changed, so an observer firing on
      // a sub-pixel wobble does not re-render the whole drawing.
      setSize(prev => (prev.width === width && prev.height === height ? prev : { width, height }));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [el]);

  return [ref, size];
}
