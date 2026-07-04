/**
 * ChartTooltip — floating overlay displayed when hovering an AreaChart.
 * Shows date, raw price/value, and cumulative return %.
 * Automatically flips left/right based on cursor position.
 */
import { memo } from 'react';

export const ChartTooltip = memo(function ChartTooltip({ tooltip }) {
  if (!tooltip) return null;
  const posStyle = tooltip.alignRight
    ? { right: Math.max(0, 98 - tooltip.pctX) + '%' }
    : { left: Math.max(0, tooltip.pctX - 2) + '%' };

  return (
    <div
      className="absolute top-0 bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-md)] px-3 py-2 pointer-events-none shadow-[var(--shadow-sm)] whitespace-nowrap z-10"
      style={posStyle}
    >
      <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] mb-1">
        {tooltip.label}
      </div>
      <div
        className="text-[15px] font-extrabold tabular-nums tracking-tight mb-0.5"
        style={{ color: tooltip.runPos ? 'var(--success)' : 'var(--danger)' }}
      >
        {tooltip.formattedValue}
      </div>
      <div
        className="font-[var(--font-mono)] text-[12px] font-semibold tabular-nums"
        style={{ color: tooltip.runPos ? 'var(--success)' : 'var(--danger)' }}
      >
        {tooltip.returnPct}
      </div>
    </div>
  );
});
