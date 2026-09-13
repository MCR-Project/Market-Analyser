/**
 * ComparisonSummary — the same five numbers for every line, side by side.
 *
 * The table exists because a chart answers "which shape" and not "by how
 * much": two lines that finish close together can have got there through
 * very different volatility and very different falls along the way.
 *
 * A line whose run failed keeps its row and says so, rather than being
 * dropped — a missing row would read as "not compared" when what happened
 * was "could not be priced".
 *
 * A money-weighted column appears as soon as any line is funded by
 * contributions (#67), and only then. RETURN and CAGR are always
 * time-weighted — they describe the holdings, not the account — which is
 * the difference the note under the table exists to name. With every line
 * funded by a single lump sum the two are the same number, and a second
 * column of it would invent a distinction.
 *
 * A cell whose metric is null carries `metrics.reasons`' explanation
 * (issue #99) via `ReasonedValue`, the same tooltip-plus-accessible-text
 * treatment PortfolioSummary gives the same three metrics.
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
  return signed ? `${value >= 0 ? '+' : '−'}${text}` : text;
}

/**
 * A cell's value, plus — when the backend named one (`metrics.reasons`,
 * issue #99) — the same tooltip-and-accessible-text treatment
 * PortfolioSummary and MdxCell give a dash they can explain.
 */
function ReasonedValue({ text, reason }) {
  if (!reason) return text;
  return (
    <span title={reason}>
      {text}
      <span className="sr-only"> — {reason}</span>
    </span>
  );
}

function tone(value) {
  if (value === null || value === undefined) return 'var(--fg-2)';
  if (value > 0) return 'var(--success)';
  if (value < 0) return 'var(--danger)';
  return 'var(--fg-1)';
}

export const ComparisonSummary = memo(function ComparisonSummary({ runs, stale }) {
  const funded = runs.some(run => (run.simulation?.metrics?.contributed || 0) > 0);

  return (
    <>
    <div
      className="overflow-x-auto border border-[var(--border)] rounded-[var(--radius-md)] mb-6"
      style={{ opacity: stale ? 0.6 : 1, transition: 'opacity 120ms' }}
    >
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-[var(--divider)]">
            <th scope="col" className="eyebrow text-left px-3 py-2 font-normal">LINE</th>
            <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">FINAL VALUE</th>
            <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">RETURN</th>
            <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">CAGR</th>
            <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">VOLATILITY</th>
            <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">MAX DRAWDOWN</th>
            {funded && (
              <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">MONEY-WEIGHTED</th>
            )}
          </tr>
        </thead>
        <tbody>
          {runs.map(run => {
            const metrics = run.simulation?.metrics;
            return (
              <tr key={run.key} className="border-b border-[var(--divider)] last:border-b-0">
                <td className="px-3 py-2.5">
                  <span className="text-[13px] font-semibold text-[var(--fg)]">{run.label}</span>
                  {run.kind === 'benchmark' && <span className="eyebrow ml-2">BENCHMARK</span>}
                </td>
                {metrics ? (
                  <>
                    <td className="px-3 py-2.5 font-[var(--font-mono)] text-[12.5px] text-right text-[var(--fg-1)]">
                      {CURRENCY.format(metrics.finalValue)}
                    </td>
                    <td className="px-3 py-2.5 font-[var(--font-mono)] text-[12.5px] text-right" style={{ color: tone(metrics.totalReturn) }}>
                      {percent(metrics.totalReturn, { signed: true })}
                    </td>
                    <td className="px-3 py-2.5 font-[var(--font-mono)] text-[12.5px] text-right" style={{ color: tone(metrics.cagr) }}>
                      <ReasonedValue text={percent(metrics.cagr, { signed: true })} reason={metrics.reasons?.cagr} />
                    </td>
                    <td className="px-3 py-2.5 font-[var(--font-mono)] text-[12.5px] text-right text-[var(--fg-1)]">
                      <ReasonedValue text={percent(metrics.volatility)} reason={metrics.reasons?.volatility} />
                    </td>
                    <td className="px-3 py-2.5 font-[var(--font-mono)] text-[12.5px] text-right" style={{ color: tone(metrics.maxDrawdown?.value) }}>
                      {percent(metrics.maxDrawdown?.value, { signed: true })}
                    </td>
                    {funded && (
                      <td className="px-3 py-2.5 font-[var(--font-mono)] text-[12.5px] text-right" style={{ color: tone(metrics.moneyWeightedReturn) }}>
                        <ReasonedValue
                          text={percent(metrics.moneyWeightedReturn, { signed: true })}
                          reason={metrics.reasons?.moneyWeightedReturn}
                        />
                      </td>
                    )}
                  </>
                ) : (
                  <td colSpan={funded ? 6 : 5} className="px-3 py-2.5 text-[12.5px] text-right text-[var(--warning)]">
                    {run.error ? 'could not be simulated over this window' : 'simulating…'}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    {funded && (
      <p className="text-[12px] text-[var(--fg-2)] leading-relaxed m-0 -mt-4 mb-6">
        <strong className="font-bold text-[var(--fg-1)]">Return</strong> and{' '}
        <strong className="font-bold text-[var(--fg-1)]">CAGR</strong> are
        time-weighted: contributions are taken out before they are measured,
        so they describe the holdings rather than the account growing.{' '}
        <strong className="font-bold text-[var(--fg-1)]">Money-weighted</strong>{' '}
        is the rate the money itself earned, counting when each payment
        arrived.
      </p>
    )}
    </>
  );
});
