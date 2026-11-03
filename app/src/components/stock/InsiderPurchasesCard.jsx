/**
 * InsiderPurchasesCard — the six-month insider buying/selling summary
 * (issue #195): exactly `services.market_data.get_stock_insider_purchases`'
 * own shape, a handful of rows, so unlike `FinancialStatementCard` this is
 * always expanded rather than starting collapsed.
 */
import { memo } from 'react';
import { useFetch } from '../../hooks/useFetch';
import { api } from '../../utils/api';
import { Loading } from '../ui/Loading';

// Shares and transaction counts, never dollars - and a few rows (the
// percent ones) are fractions rather than counts, so this reads the
// cell's own shape rather than guessing which: a whole number groups like
// one, anything else keeps up to three decimals.
function formatCell(value) {
  if (value === null || value === undefined) return '—';
  return Number.isInteger(value)
    ? value.toLocaleString('en-US')
    : value.toLocaleString('en-US', { maximumFractionDigits: 3 });
}

export const InsiderPurchasesCard = memo(function InsiderPurchasesCard({ ticker }) {
  const { data, loading, error, retry } = useFetch(
    (signal) => api.getStockInsiderPurchases(ticker, { signal }),
    [ticker],
    { fallback: null }
  );
  const rows = data?.rows ?? [];

  return (
    <section className="bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] p-5 flex flex-col gap-3">
      <div className="eyebrow">INSIDER PURCHASES</div>
      {loading ? (
        <Loading variant="skeleton" lines={3} />
      ) : error ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0">
          Insider purchases unavailable right now.{' '}
          <button
            onClick={retry}
            className="text-[var(--accent)] underline cursor-pointer bg-transparent border-none p-0 text-[13px]"
          >
            Retry
          </button>
        </p>
      ) : rows.length === 0 ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0">No insider purchase data available for this ticker.</p>
      ) : (
        <div className="overflow-x-auto border border-[var(--border)] rounded-[var(--radius-md)]">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-[var(--divider)]">
                <th scope="col" className="eyebrow text-left px-3 py-2 font-normal">LAST 6 MONTHS</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">SHARES</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">TRANSACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label} className="border-b border-[var(--divider)] last:border-b-0">
                  <td className="px-3 py-2 text-[13px] text-[var(--fg)]">{row.label}</td>
                  <td className="px-3 py-2 text-right font-[var(--font-mono)] text-[12.5px] tabular-nums text-[var(--fg)]">
                    {formatCell(row.shares)}
                  </td>
                  <td className="px-3 py-2 text-right font-[var(--font-mono)] text-[12.5px] tabular-nums text-[var(--fg)]">
                    {formatCell(row.trans)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
});
