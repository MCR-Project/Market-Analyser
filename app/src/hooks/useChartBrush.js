/**
 * useChartBrush — choosing the window by dragging across the chart.
 *
 * Presets and date boxes (#62) answer "the last five years" and "from the
 * crash to the end of 2021". Neither answers "that bit there", which is
 * the question a chart puts in front of you — so the chart itself is the
 * third control, and all three write the same window.
 *
 * Pointer events rather than mouse events, so a finger works like a
 * cursor without a second code path; the surface sets `touch-action:
 * none` so a drag selects instead of scrolling the page.
 *
 * The selection is only applied on release. Everything in between is a
 * candidate: it is drawn, its dates are shown, and nothing is simulated,
 * which is what keeps one deliberate drag to one request.
 *
 * A drag too short to mean anything is refused rather than obeyed. Below
 * a few rows the window is mostly rounding, and a stray click — which is
 * a zero-length drag — would otherwise wipe out the window entirely.
 */
import { useCallback, useRef, useState } from 'react';

/** Rows, not days: on an old window a row is a week or a month, and the
 *  point is to refuse a selection too thin to say anything either way. */
const MIN_ROWS = 4;

function clamp(value) {
  return Math.max(0, Math.min(1, value));
}

/**
 * `resolve(fraction)` maps a position across the plot (0…1) onto
 * `{ index, date }` in whatever way that chart positions its points — by
 * row for the stacked chart, by time for the comparison one.
 */
export function useChartBrush({ resolve, onSelect, minRows = MIN_ROWS }) {
  // The drag lives in a ref as well as in state: state is what the chart
  // draws, the ref is what the pointer handlers read. Deciding a
  // selection inside a setState updater would mean telling the parent
  // about it from inside one - and an updater has to be pure, so that
  // update is liable to be discarded.
  const dragRef = useRef(null);
  const [drag, setDrag] = useState(null);
  const [refused, setRefused] = useState(false);

  const fractionAt = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    return clamp((event.clientX - box.left) / box.width);
  };

  const onPointerDown = useCallback((event) => {
    // Secondary buttons belong to the browser's own menus.
    if (event.button !== undefined && event.button !== 0) return;
    // Capture keeps the drag alive when the pointer leaves the plot, so
    // selecting to the very edge does not need a steady hand. It throws
    // for a pointer the browser is not tracking, which is nothing to do
    // with the selection being made.
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // no capture, still a perfectly good drag
    }
    // Geometry is read now rather than later: React clears
    // `currentTarget` as soon as the handler returns.
    const at = fractionAt(event);
    dragRef.current = { from: at, to: at };
    setRefused(false);
    setDrag(dragRef.current);
  }, []);

  const onPointerMove = useCallback((event) => {
    if (!dragRef.current) return;
    dragRef.current = { ...dragRef.current, to: fractionAt(event) };
    setDrag(dragRef.current);
  }, []);

  const finish = useCallback((event) => {
    const current = dragRef.current;
    const surface = event?.currentTarget;
    if (surface?.hasPointerCapture?.(event.pointerId)) {
      surface.releasePointerCapture(event.pointerId);
    }
    if (!current) return;
    dragRef.current = null;
    setDrag(null);

    const from = Math.min(current.from, current.to);
    const to = Math.max(current.from, current.to);
    const a = resolve(from);
    const b = resolve(to);
    if (!a || !b || b.index - a.index < minRows) setRefused(true);
    else onSelect({ start: a.date, end: b.date });
  }, [resolve, onSelect, minRows]);

  const cancel = useCallback(() => {
    dragRef.current = null;
    setDrag(null);
  }, []);

  // Where the selection sits and what it covers, for the chart to draw
  // and label while the drag is happening.
  let selection = null;
  if (drag) {
    const from = Math.min(drag.from, drag.to);
    const to = Math.max(drag.from, drag.to);
    const a = resolve(from);
    const b = resolve(to);
    selection = {
      from,
      to,
      start: a?.date ?? null,
      end: b?.date ?? null,
      rows: a && b ? b.index - a.index : 0,
      usable: !!a && !!b && b.index - a.index >= minRows,
    };
  }

  return {
    /** Spread onto the chart's interaction surface. */
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: finish,
      onPointerCancel: cancel,
      style: { touchAction: 'none' },
    },
    selection,
    active: !!drag,
    /** True after a drag too short to be a window; cleared by the next one. */
    refused,
    dismissRefusal: () => setRefused(false),
  };
}
