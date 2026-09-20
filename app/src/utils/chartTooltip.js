/**
 * chartTooltip — what a price chart's hover readout says, given where the
 * cursor is (issue #152). Pure, so the rules a candle adds are pinned by
 * tests instead of by hovering; `useChartHover` owns the mouse and the state
 * and calls this.
 *
 * `arr` is what the chart draws, one number per hoverable thing: the closes
 * of the rows for a line, the closes of the candles for candles. For candles
 * `candleView` is `{ candles, base }`, and three things differ, all because a
 * candle is a stretch and not a point:
 *  - the label is the days the candle covers, and the readout carries its
 *    open/high/low, or says it has none;
 *  - it is placed on the candle's own slot, where the chart drew it;
 *  - the return since the window's start is measured from `base`, the first
 *    *row's* close - the figure the chart's header uses - not from the first
 *    candle's close, which is a week's or a month's last close, not the
 *    window's opening one. The tooltip and the header never disagree.
 *
 * A candle with a gap has no open/high/low here - `null`, never a formatted
 * blank or zero - and keeps its close, which every row has.
 */
import { fmtPrice } from './format';
import { PLOT_PAD, PLOT_WIDTH, candleCentre, candleLabel } from './candles';

const W = PLOT_WIDTH, PAD = PLOT_PAD;

/** The tooltip for the item at `hoverIdx`, or null when nothing is hovered
 *  (or the index is past the data). */
export function buildTooltip({ arr, hoverIdx, dates = null, candleView = null }) {
  // Not `=== undefined`: a candle with no close at all is null, and a price
  // formatter would throw on it. There is nothing true to read out there.
  if (!arr || hoverIdx == null || !Number.isFinite(arr[hoverIdx])) return null;

  const len = arr.length;
  const val = arr[hoverIdx];
  const prevVal = hoverIdx > 0 ? arr[hoverIdx - 1] : null;
  const delta = prevVal != null ? ((val - prevVal) / prevVal * 100) : null;
  const deltaPos = delta != null ? delta >= 0 : null;
  const runReturn = ((val / (candleView ? candleView.base : arr[0])) - 1) * 100;
  const runPos = runReturn >= 0;
  const pctX = candleView
    ? candleCentre(hoverIdx, len) / W * 100
    : (PAD + (hoverIdx / Math.max(1, len - 1)) * (W - 2 * PAD)) / W * 100;

  const candle = candleView ? candleView.candles[hoverIdx] : null;
  const label = candle
    ? candleLabel(candle)
    : dates && dates[hoverIdx] ? formatDate(dates[hoverIdx]) : '';

  return {
    label,
    rawValue: val,
    formattedValue: fmtPrice(val),
    returnPct: (runPos ? '+' : '') + runReturn.toFixed(2) + '%',
    runPos,
    deltaPos,
    pctX,
    alignRight: pctX >= 55,
    candle: candle
      ? {
          complete: candle.complete,
          open: candle.complete ? fmtPrice(candle.open) : null,
          high: candle.complete ? fmtPrice(candle.high) : null,
          low: candle.complete ? fmtPrice(candle.low) : null,
          close: fmtPrice(candle.close),
        }
      : null,
  };
}

function formatDate(isoDate) {
  const d = new Date(isoDate + 'T00:00:00');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
}
