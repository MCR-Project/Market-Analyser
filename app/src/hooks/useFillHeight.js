/**
 * useFillHeight — how tall a chart's plot can be so the chart ends at
 * the bottom of the visible screen (issue #139).
 *
 * The portfolio and comparison charts used to be a fixed 240px strip,
 * which on a 1080p screen left most of the results column empty below
 * them. This measures instead: the plot takes whatever height is left
 * between where it starts and the bottom of the page's scrolling area,
 * minus whatever the chart itself draws below the plot (its padding and
 * legend), clamped to [min, max].
 *
 * Measured against the page's *scroll content*, not the current scroll
 * position, so scrolling does not resize the chart under the pointer:
 * the answer is "how much of the first screenful is left", the same at
 * any scroll offset. Where the plot starts below the first screenful —
 * the stacked layout on a laptop, with the holdings table above it —
 * that is nothing, and the plot gets `min`, which is the old fixed
 * height, so a narrow screen renders exactly as it did before.
 *
 * `max` exists because a plot as tall as a 1440p monitor is a poster,
 * not a chart; past a point the extra height only stretches the bands.
 *
 * Returns `{ outerRef, plotRef, height }`. `outerRef` goes on the
 * chart's outermost element (everything from it down to the scroll area
 * is watched for size changes, so a summary loading above the chart
 * moves it); `plotRef` goes on the element whose height is `height`.
 * Both are callback refs, so a chart that renders a placeholder first
 * and its plot later — ComparisonChart's "no line could be simulated"
 * early return — starts measuring when the plot actually mounts.
 */
import { useLayoutEffect, useState } from 'react';

/** The nearest ancestor that scrolls vertically, or the document's own
 *  scrolling element when no ancestor does. */
function scrollParent(el) {
  for (let node = el.parentElement; node; node = node.parentElement) {
    const { overflowY } = getComputedStyle(node);
    if (overflowY === 'auto' || overflowY === 'scroll') return node;
  }
  return document.scrollingElement || document.documentElement;
}

export function useFillHeight(min, max) {
  const [outer, outerRef] = useState(null);
  const [plot, plotRef] = useState(null);
  const [height, setHeight] = useState(min);

  useLayoutEffect(() => {
    if (!outer || !plot) return undefined;
    const scroller = scrollParent(outer);

    const measure = () => {
      const box = scroller.getBoundingClientRect();
      const plotBox = plot.getBoundingClientRect();
      const outerBox = outer.getBoundingClientRect();
      const padBottom = parseFloat(getComputedStyle(scroller).paddingBottom) || 0;
      // Where the plot starts within the scroll content, independent of
      // how far that content is scrolled right now.
      const plotTop = plotBox.top - box.top + scroller.scrollTop;
      // Everything the chart draws under its plot. Its own height is
      // not in here, so resizing the plot cannot change this number.
      const below = outerBox.bottom - plotBox.bottom;
      const available = scroller.clientHeight - padBottom - plotTop - below;
      const next = Math.round(Math.min(max, Math.max(min, available)));
      setHeight(prev => (prev === next ? prev : next));
    };

    // The scroll area resizing (the window) and anything between it and
    // the chart resizing (content above loading, the layout switching
    // between stacked and columns) both move where the plot can end.
    // The plot's own growth also resizes these ancestors; measuring then
    // gives the same answer, so it settles instead of looping.
    const observer = new ResizeObserver(measure);
    for (let node = outer; node && node !== scroller; node = node.parentElement) {
      observer.observe(node);
    }
    observer.observe(scroller);
    measure();
    return () => observer.disconnect();
  }, [outer, plot, min, max]);

  return { outerRef, plotRef, height };
}
