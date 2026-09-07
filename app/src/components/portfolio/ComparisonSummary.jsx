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

function tone(value) {
  if (value === null || value === undefined) return 'var(--fg-2)';
  if (value > 0) return 'var(--success)';
  if (value < 0) return 'var(--danger)';
  return 'var(--fg-1)';
}

export const ComparisonSummary = memo(function ComparisonSummary({ runs, stale }) {
  return (
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
                      {percent(metrics.cagr, { signed: true })}
                    </td>
                    <td className="px-3 py-2.5 font-[var(--font-mono)] text-[12.5px] text-right text-[var(--fg-1)]">
                      {percent(metrics.volatility)}
                    </td>
                    <td className="px-3 py-2.5 font-[var(--font-mono)] text-[12.5px] text-right" style={{ color: tone(metrics.maxDrawdown?.value) }}>
                      {percent(metrics.maxDrawdown?.value, { signed: true })}
                    </td>
                  </>
                ) : (
                  <td colSpan={5} className="px-3 py-2.5 text-[12.5px] text-right text-[var(--warning)]">
                    {run.error ? 'could not be simulated over this window' : 'simulating…'}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
});
