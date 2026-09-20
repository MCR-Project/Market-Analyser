/**
 * CandleChart — the candle view of a price chart (issue #152), drawn in the
 * same 360-unit plot, with the same hover surface, as `AreaChart` so the two
 * swap in place.
 *
 * One body and one wick per candle: the body runs open to close, the wick low
 * to high. Green (--color-success) when the candle closed at or above where it
 * opened, red otherwise - a rule about the candle itself, not against the
 * previous candle's close, so a day that gapped down and recovered still
 * reads as up. The line chart's colour (the whole window's return) is a
 * different question and is untouched by this.
 *
 * A candle with a gap (`complete: false`) draws nothing: a flat candle would
 * claim the price did not move. The vertical scale is fitted to the candles
 * that are drawn, so a gap never stretches it.
 *
 * Stretched to its box like the other charts, hence no text in the SVG, and
 * strokes that do not scale (`vectorEffect`) so a wick stays a wick at any
 * width. A candle whose open equals its close still gets a hairline body: it
 * has a range, and the wick alone would look like a candle with no body at
 * all.
 *
 * Props: candles, hoverIdx, onMouseMove/Leave, height (px).
 */
import { memo, useMemo } from 'react';
import { PLOT_PAD, PLOT_WIDTH, candleCentre, candleSlotWidth } from '../../utils/candles';

const W = PLOT_WIDTH;
const MAX_BODY = 12;   // units - keeps a five-candle week from becoming five slabs
const BODY_SHARE = 0.7;

export const CandleChart = memo(function CandleChart({ candles, hoverIdx, onMouseMove, onMouseLeave, height = 140 }) {
  const H = height;

  const drawn = useMemo(() => {
    const complete = candles.filter((c) => c.complete);
    if (!complete.length) return [];
    const min = Math.min(...complete.map((c) => c.low));
    const max = Math.max(...complete.map((c) => c.high));
    const span = (max - min) || 1;
    const vertPad = PLOT_PAD + 6;
    const y = (price) => vertPad + (1 - (price - min) / span) * (H - 2 * vertPad);
    const slot = candleSlotWidth(candles.length);
    const bodyWidth = Math.min(slot * BODY_SHARE, MAX_BODY);

    return candles.flatMap((c, i) => {
      if (!c.complete) return [];
      const cx = candleCentre(i, candles.length);
      const top = y(Math.max(c.open, c.close));
      const bottom = y(Math.min(c.open, c.close));
      return [{
        key: i,
        up: c.close >= c.open,
        cx,
        bodyX: cx - bodyWidth / 2,
        bodyWidth,
        bodyTop: top,
        bodyHeight: Math.max(bottom - top, 1),
        wickTop: y(c.high),
        wickBottom: y(c.low),
      }];
    });
  }, [candles, H]);

  const slot = candleSlotWidth(candles.length);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      width="100%"
      className="block overflow-visible"
      style={{ height: H + 'px' }}
      role="img"
      aria-label={`Candlestick chart, ${candles.length} candles`}
    >
      {hoverIdx != null && (
        <rect
          x={candleCentre(hoverIdx, candles.length) - slot / 2} y={0}
          width={slot} height={H}
          fill="var(--bg-3)" opacity={0.7}
        />
      )}
      {drawn.map((d) => {
        const color = d.up ? 'var(--color-success)' : 'var(--color-danger)';
        return (
          <g key={d.key}>
            <line
              x1={d.cx} x2={d.cx} y1={d.wickTop} y2={d.wickBottom}
              stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke"
            />
            <rect
              x={d.bodyX} y={d.bodyTop} width={d.bodyWidth} height={d.bodyHeight}
              fill={color} stroke={color} strokeWidth={1} vectorEffect="non-scaling-stroke"
            />
          </g>
        );
      })}
      <rect x={0} y={0} width={W} height={H} fill="transparent" onMouseMove={onMouseMove} onMouseLeave={onMouseLeave} style={{ cursor: 'crosshair' }} />
    </svg>
  );
});
