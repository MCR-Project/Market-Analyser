/**
 * useChartHover — manages hover state for AreaChart and CandleChart.
 *
 * Converts mouse X position to a data index; what the tooltip then says is
 * `utils/chartTooltip.js`'s `buildTooltip` (date label, return %, period
 * delta, raw value - and, over a candle, its open/high/low).
 *
 * The date label comes solely from the `dates` array (ISO strings from
 * the API) — no mock/computed label fallback.
 *
 * `candleView` (issue #152) is `{ candles, base }` when the chart is drawing
 * candles, and then `arr` is the candles' closes. The cursor then finds a
 * candle by its slot (`utils/candles.js`'s `candleIndexAt`, the same function
 * the chart draws with) rather than the nearest of evenly spaced points.
 */
import { useState, useCallback } from 'react';
import { buildTooltip } from '../utils/chartTooltip';
import { PLOT_PAD, PLOT_WIDTH, candleIndexAt } from '../utils/candles';

const W = PLOT_WIDTH, PAD = PLOT_PAD;

export function useChartHover(arr, timeframe, dates = null, candleView = null) {
  const [hoverIdx, setHoverIdx] = useState(null);
  const len = arr?.length ?? 0;
  const slotted = candleView != null;

  const onMouseMove = useCallback((e) => {
    if (!len) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width;
    const i = slotted
      ? candleIndexAt(relX * W, len)
      : Math.round(
          Math.max(0, Math.min(1, (relX * W - PAD) / (W - 2 * PAD))) * (len - 1)
        );
    setHoverIdx(prev => prev === i ? prev : i);
  }, [len, slotted]);

  const onMouseLeave = useCallback(() => {
    setHoverIdx(null);
  }, []);

  const tooltip = buildTooltip({ arr, hoverIdx, dates, candleView });

  return { hoverIdx, onMouseMove, onMouseLeave, tooltip };
}
