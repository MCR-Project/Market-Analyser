/**
 * ChartTooltip — floating overlay displayed when hovering a price chart.
 * Shows date, raw price/value, and cumulative return %.
 * Automatically flips left/right based on cursor position.
 *
 * Over a candle (issue #152) `tooltip.candle` is set and the one price line
 * becomes the candle's open, high, low and close, with the return since the
 * window's start beneath. A candle with a gap has no such prices and says so,
 * keeping the close it does have - never a row of dashes that could be read
 * as a price of nothing.
 */
import { memo } from 'react';

export const ChartTooltip = memo(function ChartTooltip({ tooltip }) {
  if (!tooltip) return null;
  const posStyle = tooltip.alignRight
    ? { right: Math.max(0, 98 - tooltip.pctX) + '%' }
    : { left: Math.max(0, tooltip.pctX - 2) + '%' };
  const tone = tooltip.runPos ? 'var(--success)' : 'var(--danger)';
  const { candle } = tooltip;

  return (
    <div
      className="absolute top-0 bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-md)] px-3 py-2 pointer-events-none shadow-[var(--shadow-sm)] whitespace-nowrap z-10"
      style={posStyle}
    >
      <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] mb-1">
        {tooltip.label}
      </div>
      {candle?.complete ? (
        <div className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 mb-1 font-[var(--font-mono)] text-[12px] tabular-nums text-[var(--fg)]">
          <Price name="O" value={candle.open} />
          <Price name="H" value={candle.high} />
          <Price name="L" value={candle.low} />
          <Price name="C" value={candle.close} />
        </div>
      ) : (
        <>
          {candle && (
            <div className="font-[var(--font-mono)] text-[11px] text-[var(--fg-3)] mb-1">
              no open/high/low
            </div>
          )}
          <div
            className="text-[15px] font-extrabold tabular-nums tracking-tight mb-0.5"
            style={{ color: tone }}
          >
            {tooltip.formattedValue}
          </div>
        </>
      )}
      <div
        className="font-[var(--font-mono)] text-[12px] font-semibold tabular-nums"
        style={{ color: tone }}
      >
        {tooltip.returnPct}
      </div>
    </div>
  );
});

function Price({ name, value }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[10px] text-[var(--fg-3)]">{name}</span>
      <span>{value}</span>
    </div>
  );
}
