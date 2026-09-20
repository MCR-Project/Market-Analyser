/**
 * PortfolioMetricWorkedExample — the real number behind a portfolio
 * metric's doc page (issue #104).
 *
 * The portfolio-metric counterpart to WorkedExample.jsx, and much
 * narrower: there is no per-ticker table to sample, because a portfolio
 * metric describes a whole run, not one holding. This shows three
 * things instead — the example portfolio, the window it actually
 * simulated over, and this metric's own value from that real run — and
 * is what DocMdx.jsx's `<WorkedExample />` tag renders for a portfolio
 * metric's doc (see PortfolioMetricDoc.jsx, which supplies this as
 * DocMdx's `WorkedExampleComponent`).
 *
 * **The computed value is real**, the same load-bearing rule the
 * measurement version states: `simulate_portfolio` runs against the
 * documented example portfolio exactly as a normal simulation would, and
 * the value shown is read straight out of that response. A
 * computed_from="risk" metric (issue #113) reuses this same rendering
 * path against `compute_portfolio_risk`'s own response instead — the
 * backend's `examples.py` shapes that payload identically
 * (`{portfolio, run, value, reason}`) precisely so this component needs
 * no branch of its own beyond `isRiskExample`'s small wording tweak
 * below (no simulated value, no contribution schedule to mention).
 */
import { memo } from 'react';
import { useFetch } from '../../hooks/useFetch';
import { api } from '../../utils/api';
import { Loading } from '../ui/Loading';

const CURRENCY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

/** A metric's raw value, by shape: a drawdown-style {value, peakDate,
 *  troughDate} object, a list (incomeUnknownFor), a per-holding breakdown
 *  (riskShare, issue #113 — one percent per ticker, no "value" key of its
 *  own to distinguish it from a drawdown object), or a plain number. */
function formatValue(value) {
  if (value === null || value === undefined) return '—';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '(none)';
  if (typeof value === 'object' && 'value' in value) {
    return value.peakDate
      ? `${value.value}% (${value.peakDate} → ${value.troughDate})`
      : `${value.value}%`;
  }
  if (typeof value === 'object') {
    return Object.entries(value).map(([ticker, share]) => `${ticker} ${share}%`).join(', ');
  }
  return String(value);
}

// A computed_from="risk" example (issue #113) is computed live, not
// simulated - compute_portfolio_risk never walks the window day by day
// the way simulate_portfolio does - so the sentence above the result
// says so, and drops the contribution clause: a risk read pays no
// attention to money paid in on a schedule.
function isRiskExample(runMetrics) {
  return 'riskShare' in (runMetrics || {}) || 'effectiveBets' in (runMetrics || {});
}

export const PortfolioMetricWorkedExample = memo(function PortfolioMetricWorkedExample({ measurementId }) {
  const { data, loading, error } = useFetch(
    (signal) => api.getPortfolioMetricExample(measurementId, { signal }),
    [measurementId],
    { fallback: null }
  );

  if (loading) {
    return (
      <section className="my-6">
        <SectionHeading>Worked example</SectionHeading>
        <Loading variant="skeleton" lines={5} />
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="my-6">
        <SectionHeading>Worked example</SectionHeading>
        <p className="text-[13px] text-[var(--fg-2)] m-0">
          The live example could not be computed right now, so it is not
          shown — the explanation above still applies.
        </p>
      </section>
    );
  }

  // A computed_from="etf_id" entry (issue #105) has no run to show —
  // it's computed live against the documented example fund instead.
  if (!data.portfolio) {
    return (
      <section className="my-6">
        <SectionHeading>Worked example</SectionHeading>
        <p className="text-[13px] text-[var(--fg-2)] mt-0 mb-4">
          Computed live for{' '}
          <strong className="text-[var(--fg)] font-semibold">{data.etf_id}</strong>,
          the fund this documentation defaults to.
        </p>

        <div className="border border-[var(--border)] rounded-[var(--radius-md)] overflow-hidden">
          <div className="px-4 py-2.5 bg-[var(--bg-2)] border-b border-[var(--border)]">
            <span className="font-[var(--font-mono)] text-[12px] font-bold text-[var(--fg)]">result</span>
          </div>
          <div className="px-4 py-3.5">
            <div className="font-[var(--font-mono)] text-[22px] font-bold text-[var(--fg)] tabular-nums">
              {formatValue(data.value)}
            </div>
            {data.reason && (
              <p className="text-[12px] text-[var(--fg-2)] mt-1.5 mb-0">{data.reason}</p>
            )}
          </div>
        </div>
      </section>
    );
  }

  const { portfolio, run, value, reason } = data;
  const holdings = portfolio.holdings || [];
  const risk = isRiskExample(run.metrics);
  const contribution = !risk && portfolio.contribution;
  // The example's own schedule, of whichever kind (#150): Withdrawn's page
  // names a portfolio that draws out, and the sentence has to say so.
  const withdrawal = !risk && portfolio.withdrawal;

  return (
    <section className="my-6">
      <SectionHeading>Worked example</SectionHeading>
      <p className="text-[13px] text-[var(--fg-2)] mt-0 mb-4">
        {risk ? 'Computed live for a basket of' : `Simulated live for a ${CURRENCY.format(portfolio.value || 10_000)} portfolio of`}{' '}
        {holdings.map((h, i) => (
          <span key={h.ticker}>
            {i > 0 && ', '}
            <strong className="text-[var(--fg)] font-semibold">{h.ticker}</strong> {h.weight}%
          </span>
        ))}
        {contribution && (
          <> plus {CURRENCY.format(contribution.amount)} {contribution.frequency}</>
        )}
        {withdrawal && (
          <> less {CURRENCY.format(withdrawal.amount)} {withdrawal.frequency}</>
        )}, from{' '}
        <strong className="text-[var(--fg)] font-semibold">{run.start}</strong> to{' '}
        <strong className="text-[var(--fg)] font-semibold">{run.end}</strong>.
      </p>

      <div className="border border-[var(--border)] rounded-[var(--radius-md)] overflow-hidden">
        <div className="px-4 py-2.5 bg-[var(--bg-2)] border-b border-[var(--border)]">
          <span className="font-[var(--font-mono)] text-[12px] font-bold text-[var(--fg)]">result</span>
        </div>
        <div className="px-4 py-3.5">
          <div className="font-[var(--font-mono)] text-[22px] font-bold text-[var(--fg)] tabular-nums">
            {formatValue(value)}
          </div>
          {reason && (
            <p className="text-[12px] text-[var(--fg-2)] mt-1.5 mb-0">{reason}</p>
          )}
        </div>
      </div>
    </section>
  );
});

function SectionHeading({ children }) {
  return (
    <h2 className="text-[19px] font-bold text-[var(--fg)] tracking-tight mt-8 mb-2.5 pb-1.5 border-b border-[var(--divider)]">
      {children}
    </h2>
  );
}
