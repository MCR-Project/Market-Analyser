/**
 * useTableFloor — the minimum height that keeps the holdings table showing
 * its first few holdings, measured from the table itself.
 *
 * `rootRef` goes on the table view's outermost element and `rowsRef` on the
 * scrolling box that holds the rows; each row carries `data-holding-row`.
 * `minHeight` is that root's floor in pixels (null until the first
 * measurement, which happens before the first paint). The arithmetic is
 * `utils/tableFloor.js`; this only reads the numbers off the page.
 *
 * Nothing here hardcodes a row: the row height is read from a drawn row, so
 * the floor rises when the metric columns wrap and rows grow. The last
 * height read is kept, so a search that matches nothing, or a reload in
 * progress, does not drop the floor and make the table jump under the
 * cursor — the panel stays the size it was.
 *
 * The chrome (toolbar, headers, filter row, borders) is the root's height
 * minus the rows box's, so it is not tied to any one element's markup. Both
 * are callback refs, for the same reason as useElementSize: the rows box
 * mounts after a loading state and measuring starts when it does.
 */
import { useLayoutEffect, useRef, useState } from 'react';
import { tableFloor } from '../utils/tableFloor';

const ROW = '[data-holding-row]';

const px = (value) => parseFloat(value) || 0;

export function useTableFloor(firstRowKey) {
  const [root, rootRef] = useState(null);
  const [rows, rowsRef] = useState(null);
  const [minHeight, setMinHeight] = useState(null);
  const lastRowHeight = useRef(null);

  // `firstRowKey` is not read here: it changes when the first drawn row
  // does (loading finishing, a filter emptying the list), which is when the
  // row being observed has to be looked up again.
  useLayoutEffect(() => {
    if (!root || !rows) return undefined;

    const measure = () => {
      const row = rows.querySelector(ROW);
      if (row) lastRowHeight.current = row.getBoundingClientRect().height;
      const style = getComputedStyle(rows);
      const next = tableFloor({
        chrome: root.getBoundingClientRect().height - rows.getBoundingClientRect().height,
        rowHeight: lastRowHeight.current,
        gap: px(style.rowGap),
        padding: px(style.paddingTop) + px(style.paddingBottom),
      });
      // The floor moves the root, which moves the rows box, which measures
      // again. The chrome is the same either way, so it settles.
      setMinHeight(prev => (prev === next ? prev : next));
    };

    const observer = new ResizeObserver(measure);
    observer.observe(root);
    observer.observe(rows);
    const row = rows.querySelector(ROW);
    if (row) observer.observe(row);
    measure();
    return () => observer.disconnect();
  }, [root, rows, firstRowKey]);

  return { rootRef, rowsRef, minHeight };
}
