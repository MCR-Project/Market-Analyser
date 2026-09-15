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
 * the value shown is read straight out of that response.
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
 *  troughDate} object, a list (incomeUnknownFor), or a plain number. */
function formatValue(value) {
  if (value === null || value === undefined) return '—';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '(none)';
  if (typeof value === 'object' && 'value' in value) {
    return value.peakDate
      ? `${value.value}% (${value.peakDate} → ${value.troughDate})`
      : `${value.value}%`;
  }
  return String(value);
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

  // A computed_from="etf_id" entry (issue #105) has no run to show; none
  // shipped today actually reaches this branch.
  if (!data.portfolio) {
    return (
      <section className="my-6">
        <SectionHeading>Worked example</SectionHeading>
        <p className="text-[13px] text-[var(--fg-2)] m-0">
          This metric is computed from a fund rather than a simulated
          portfolio; its worked example ships with the metric that uses it.
        </p>
      </section>
    );
  }

  const { portfolio, run, value, reason } = data;
  const holdings = portfolio.holdings || [];
  const contribution = portfolio.contribution;

  return (
    <section className="my-6">
      <SectionHeading>Worked example</SectionHeading>
      <p className="text-[13px] text-[var(--fg-2)] mt-0 mb-4">
        Simulated live for a {CURRENCY.format(portfolio.value || 10_000)} portfolio of{' '}
        {holdings.map((h, i) => (
          <span key={h.ticker}>
            {i > 0 && ', '}
            <strong className="text-[var(--fg)] font-semibold">{h.ticker}</strong> {h.weight}%
          </span>
        ))}
        {contribution && (
          <> plus {CURRENCY.format(contribution.amount)} {contribution.frequency}</>
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
