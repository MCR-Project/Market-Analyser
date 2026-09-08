/**
 * PortfolioSummary — how the run went, in one line.
 *
 * The numbers the simulation reports about the whole portfolio (see
 * backend/services/portfolio.py for what each one means and the
 * conventions behind it). They sit above the chart because they are the
 * answer; the chart is the explanation.
 *
 * A number the run could not support comes back null rather than zero — a
 * two-day window has no growth rate and no volatility — and shows as a
 * dash. Zero would be a claim, and the wrong one.
 *
 * **Once money keeps arriving there are two questions, and the summary
 * splits into two rows to stop them being read as one** (#67). The top
 * row is the portfolio: total return, CAGR, volatility and drawdown, all
 * time-weighted, all describing what a dollar left alone in it would have
 * done. The second row is the account: what was paid in, what was gained,
 * and the money-weighted return, which accounts for a deposit made last
 * week having had a week to work. A portfolio can return 54% while the
 * money in it earns 21% a year, and neither number is wrong.
 *
 * The second row appears only when something was actually contributed.
 * With a single lump sum the two questions have the same answer, and
 * printing it twice under two headings would imply a distinction that is
 * not there.
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

function tone(value) {
  if (value > 0) return 'var(--success)';
  if (value < 0) return 'var(--danger)';
  return 'var(--fg)';
}

export const PortfolioSummary = memo(function PortfolioSummary({ metrics, stale }) {
  const drawdown = metrics.maxDrawdown || {};
  const contributed = metrics.contributed || 0;
  const funded = contributed > 0;

  return (
    <div
      className="mb-4 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)]"
      style={{ opacity: stale ? 0.6 : 1, transition: 'opacity 120ms' }}
    >
      {funded && (
        <div className="eyebrow px-5 pt-4 pb-0">
          THE PORTFOLIO · TIME-WEIGHTED, SO DEPOSITS DO NOT COUNT AS GAINS
        </div>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-5 p-5">
        <Stat label="FINAL VALUE" value={CURRENCY.format(metrics.finalValue)} />
        <Stat
          label="TOTAL RETURN"
          value={percent(metrics.totalReturn, { signed: true })}
          tone={tone(metrics.totalReturn)}
          title={
            funded
              ? 'What the holdings returned over the window, with contributions taken out — not what the account grew by'
              : 'What the portfolio returned over the window'
          }
        />
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

      {funded && (
        <>
          <div className="eyebrow px-5 pt-4 pb-0 border-t border-[var(--divider)]">
            THE ACCOUNT · MONEY-WEIGHTED, SO WHEN EACH DOLLAR ARRIVED COUNTS
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-5 p-5 pt-4">
            <Stat
              label="PAID IN"
              value={CURRENCY.format(metrics.totalInvested)}
              title="The opening amount plus every contribution"
            />
            <Stat
              label="CONTRIBUTED"
              value={CURRENCY.format(contributed)}
              title="The contributions on their own, without the opening amount"
            />
            <Stat
              label="GAIN"
              value={`${metrics.gain >= 0 ? '+' : '−'}${CURRENCY.format(Math.abs(metrics.gain))}`}
              tone={tone(metrics.gain)}
              title="Final value less everything paid in — the money the portfolio actually made"
            />
            <Stat
              label="MONEY-WEIGHTED"
              value={percent(metrics.moneyWeightedReturn, { signed: true })}
              tone={tone(metrics.moneyWeightedReturn)}
              title="Internal rate of return: the annual rate that reconciles every deposit, from the day it arrived, with the final value"
            />
          </div>
        </>
      )}
    </div>
  );
});
