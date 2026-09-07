/**
 * PortfolioSummary — how the run went, in one line.
 *
 * The five numbers the simulation reports about the whole portfolio (see
 * backend/services/portfolio.py for what each one means and the
 * conventions behind it). They sit above the chart because they are the
 * answer; the chart is the explanation.
 *
 * A number the run could not support comes back null rather than zero — a
 * two-day window has no growth rate and no volatility — and shows as a
 * dash. Zero would be a claim, and the wrong one.
 */
import { memo } from 'react';

const CURRENCY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

function percent(value, { signed = false } = {}) {
  if (value === null || value === undefined) return '—';
  const text = `${Math.abs(value).toFixed(1)}%`;
  if (!signed) return text;
  return `${value >= 0 ? '+' : '−'}${text}`;
}

function Stat({ label, value, tone, title }) {
  return (
    <div title={title}>
      <div className="eyebrow mb-1">{label}</div>
      <div
        className="text-[15px] font-extrabold tabular-nums tracking-tight"
        style={{ color: tone || 'var(--fg)' }}
      >
        {value}
      </div>
    </div>
  );
}

export const PortfolioSummary = memo(function PortfolioSummary({ metrics, stale }) {
  const drawdown = metrics.maxDrawdown || {};
  const returnTone = metrics.totalReturn > 0
    ? 'var(--success)'
    : metrics.totalReturn < 0 ? 'var(--danger)' : 'var(--fg)';

  return (
    <div
      className="grid grid-cols-2 sm:grid-cols-5 gap-5 p-5 mb-4 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)]"
      style={{ opacity: stale ? 0.6 : 1, transition: 'opacity 120ms' }}
    >
      <Stat label="FINAL VALUE" value={CURRENCY.format(metrics.finalValue)} />
      <Stat label="TOTAL RETURN" value={percent(metrics.totalReturn, { signed: true })} tone={returnTone} />
      <Stat
        label="CAGR"
        value={percent(metrics.cagr, { signed: true })}
        title="Compound annual growth rate over the calendar time the window covers"
      />
      <Stat
        label="VOLATILITY"
        value={percent(metrics.volatility)}
        title="Annualised standard deviation of the run's returns"
      />
      <Stat
        label="MAX DRAWDOWN"
        value={percent(drawdown.value, { signed: true })}
        tone={drawdown.value < 0 ? 'var(--danger)' : 'var(--fg)'}
        title={
          drawdown.peakDate
            ? `Deepest fall, from ${drawdown.peakDate} to ${drawdown.troughDate}`
            : 'The portfolio never fell below a previous peak in this window'
        }
      />
    </div>
  );
});
