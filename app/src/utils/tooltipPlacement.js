/**
 * tooltipPlacement — where a chart's hover tooltip sits relative to the
 * date being hovered (issue #177). Pure, so the rules are pinned by tests
 * instead of by hovering; every chart that has a tooltip asks this and none
 * works out its own offset.
 *
 * The tooltip is *beside* the hover line, never over it: it used to start 2%
 * before the line (or end 2% after it), which put it on the very date being
 * read. Now it sits on whichever side of the line has the room — to the right
 * of it in the left part of the chart, to the left of it from FLIP_AT on —
 * with TOOLTIP_GAP pixels of air between its near edge and the line. It stays
 * where it was vertically, at the top of the plot; it still covers other
 * dates, never the hovered one.
 *
 * The position is returned as one CSS offset on one side — `left` or
 * `right`, never both, so the tooltip keeps its own width — written as a
 * `calc()`, because the line is at a share of the plot's width and the gap
 * is in pixels. `pctX` is the line's position in percent of the plot.
 *
 *  - `clearPct` is room to leave beyond the line itself, in percent of the
 *    plot. A candle chart has no line but shades the hovered candle's whole
 *    slot, which is what must stay visible, so it asks for half a slot.
 *
 * The box the tooltip is positioned in must be the plot itself, so that a
 * percentage of it is a position on the plot. The price charts' hosts are, and
 * the two portfolio charts, which sit their plot inside padding, wrap the
 * drawing and its tooltip in a box of exactly the plot's size for it.
 */

/** The air, in pixels, between the line (or the shaded slot) and the tooltip. */
export const TOOLTIP_GAP = 14;

/** From this position (percent of the plot) on, the tooltip moves to the
 *  line's left, where there is more room than to its right. */
export const FLIP_AT = 55;

export function tooltipPlacement({ pctX, clearPct = 0 }) {
  const onLeft = pctX >= FLIP_AT;
  // How far the tooltip's near edge is from the plot's edge on its own side
  // of the line, as a share of the plot: the line's position plus the
  // clearance going one way, the rest of the plot minus it going the other.
  const share = onLeft ? 100 - pctX + clearPct : pctX + clearPct;
  const side = onLeft ? 'right' : 'left';
  return { [side]: `calc(${share}% + ${TOOLTIP_GAP}px)` };
}
