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
 * dash. Zero would be a claim, and the wrong one. When the backend can say
 * why (`metrics.reasons`, issue #99 — the same optional sidecar a
 * measurement column's `per_ticker_reason` is), the dash carries that
 * reason as a tooltip and as real accessible text, not just a generic
 * description of what the metric usually means.
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
 *
 * **Dividend income is a sentence, not a tile** (#68). Every figure above
 * is already a total return — `prices` stores adjusted closes (#13), so
 * the income was spent on more of the same holding the moment it arrived.
 * The thing worth saying is therefore a *relationship*: how much of what
 * is already there came from being paid rather than from the price
 * moving, and that it is not to be added on top. A tile reading
 * "DIVIDENDS $1,234" beside "FINAL VALUE" invites exactly the addition
 * the note exists to prevent.
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

/**
 * `reason` (issue #99) is why *this* run's value is a dash — read off
 * `metrics.reasons`, the portfolio's own version of a measurement
 * column's `per_ticker_reason` — and takes over the tooltip from the
 * generic `title` when the two would otherwise compete: a reader looking
 * at a dash wants to know why this run has none, not what the metric
 * means in general. `title` alone is not reliably announced to a screen
 * reader, so the reason also gets its own `sr-only` text, same rule
 * MdxCell follows for a measurement cell's dash.
 */
function Stat({ label, value, tone, title, reason }) {
  return (
    <div title={reason || title}>
      <div className="eyebrow mb-1">{label}</div>
      <div
        className="text-[15px] font-extrabold tabular-nums tracking-tight"
        style={{ color: tone || 'var(--fg)' }}
      >
        {value}
      </div>
      {reason && <span className="sr-only"> — {reason}</span>}
    </div>
  );
}

/**
 * Why the returns above are already total returns, and what the income
 * inside them came to.
 *
 * Always shown, including when the answer is nothing: "these are total
 * returns and this portfolio paid no income" is a useful thing to learn,
 * and a note that appeared only for payers would leave everyone else
 * wondering whether dividends were counted at all.
 */
function DividendNote({ metrics }) {
  const income = metrics.dividendIncome;
  if (income === null || income === undefined) return null;
  const unknown = metrics.incomeUnknownFor || [];

  return (
    <p className="text-[12px] text-[var(--fg-2)] leading-relaxed m-0 px-5 pb-4 -mt-1">
      <strong className="font-bold text-[var(--fg-1)]">These are total returns.</strong>{' '}
      Prices here are dividend-adjusted, so the figures above already
      include income —{' '}
      {income > 0 ? (
        <>
          <strong className="font-bold text-[var(--fg-1)]">{CURRENCY.format(income)}</strong>{' '}
          of it over this window, {percent(metrics.dividendYield)} of everything
          paid in. It is counted where it was reinvested rather than added on
          top, which would be the same money twice.
        </>
      ) : (
        <>and over this window there was none to include.</>
      )}
      {unknown.length > 0 && (
        <>
          {' '}
          <span className="text-[var(--warning)]">
            {unknown.join(', ')} {unknown.length === 1 ? 'is a fund whose' : 'are funds whose'}{' '}
            dividends are not on record here, so {unknown.length === 1 ? 'its' : 'their'}{' '}
            income is missing from that figure — the value and the return still
            include it.
          </span>
        </>
      )}
    </p>
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
          reason={metrics.reasons?.cagr}
        />
        <Stat
          label="VOLATILITY"
          value={percent(metrics.volatility)}
          title="Annualised standard deviation of the run's returns"
          reason={metrics.reasons?.volatility}
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

      <DividendNote metrics={metrics} />

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
              reason={metrics.reasons?.moneyWeightedReturn}
            />
          </div>
        </>
      )}
    </div>
  );
});
