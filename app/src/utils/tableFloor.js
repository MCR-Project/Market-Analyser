/**
 * tableFloor — how tall the holdings table must be to show its first few
 * holdings, however short the window is.
 *
 * The Table view takes whatever height is left below the ETF card and the
 * tabs, and inside a scrolling page that can be nothing: on a short window
 * the header and the filter row were all that showed, with no holding under
 * them. The floor is the height below which the page scrolls instead of the
 * table shrinking.
 *
 * It is counted in holdings, not pixels, because a row's height is not a
 * constant: the metric columns wrap onto a second line when enough of them
 * are on (TableView.jsx), so every row gets taller together. The caller
 * measures a real row; this only does the arithmetic, and says what to use
 * before any row has been drawn.
 *
 * `chrome` is everything in the table view that is not the rows' scrolling
 * box — the toolbar, the column headers, the filter row, borders and
 * margins. `padding` is that box's own top and bottom padding, which is
 * inside it but is not a row. `gap` is the space between two rows.
 */

/** How many holdings the table always shows. */
export const FLOOR_ROWS = 5;

/** A row's height when none has been drawn yet (loading, or a search that
 *  matched nothing) and none ever was: the identity cell of a row with no
 *  metric columns. Only a stand-in until the first measurement replaces it. */
export const ESTIMATED_ROW_HEIGHT = 86;

export function tableFloor({ chrome, rowHeight, gap, padding, rows = FLOOR_ROWS }) {
  const row = rowHeight > 0 ? rowHeight : ESTIMATED_ROW_HEIGHT;
  // Rounded up: a floor a fraction of a pixel short would clip the last
  // row's border.
  return Math.ceil(chrome + padding + rows * row + (rows - 1) * gap);
}
