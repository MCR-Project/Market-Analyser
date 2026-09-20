/**
 * PriceChart — a price history drawn as a line or as candles, whichever the
 * one shared switch says (issue #152), with its hover and tooltip.
 *
 * The three places that chart a price - the fund card, StockPopup and
 * HoldingChartPopup - all render this, so the choice between the two drawings,
 * and the hover that goes with each, is made in exactly one place. It renders
 * a fragment: the caller supplies the `relative` box the tooltip positions
 * against, and decides what shows while the series is still loading.
 *
 * `arr` and `dates` are one entry per row the API answered; `candles` is the
 * same rows resampled (`useLiveSeries`). The line is always drawn from the
 * rows and the return figures always come from them, so switching drawings
 * changes what the chart looks like and nothing it says about how the window
 * went.
 *
 * Props: arr, dates, candles, pct (window return %, colours the line),
 * timeframe, gradientId, height (px).
 */
import { memo, useMemo } from 'react';
import { useCandles } from '../../hooks/useCandles';
import { useChartHover } from '../../hooks/useChartHover';
import { AreaChart } from './AreaChart';
import { CandleChart } from './CandleChart';
import { ChartTooltip } from './ChartTooltip';

export const PriceChart = memo(function PriceChart({ arr, dates, candles, pct, timeframe, gradientId, height }) {
  const [candlesOn] = useCandles();
  const asCandles = candlesOn && candles != null;

  const candleCloses = useMemo(() => candles?.map((c) => c.close) ?? null, [candles]);
  const candleView = useMemo(
    () => (asCandles ? { candles, base: arr[0] } : null),
    [asCandles, candles, arr]
  );

  const { hoverIdx, onMouseMove, onMouseLeave, tooltip } = useChartHover(
    asCandles ? candleCloses : arr, timeframe, dates, candleView
  );

  const nothingToDraw = asCandles && !candles.some((c) => c.complete);

  return (
    <>
      {asCandles ? (
        <CandleChart candles={candles} hoverIdx={hoverIdx} onMouseMove={onMouseMove} onMouseLeave={onMouseLeave} height={height} />
      ) : (
        <AreaChart data={arr} pct={pct} hoverIdx={hoverIdx} onMouseMove={onMouseMove} onMouseLeave={onMouseLeave} gradientId={gradientId} height={height} />
      )}
      {nothingToDraw && (
        <div className="absolute inset-0 grid place-items-center pointer-events-none text-xs text-[var(--fg-3)] text-center px-4">
          No open, high or low to draw for this window
        </div>
      )}
      <ChartTooltip tooltip={tooltip} />
    </>
  );
});
