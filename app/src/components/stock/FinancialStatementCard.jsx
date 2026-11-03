/**
 * FinancialStatementCard — shared table card for the Stock page's Balance
 * Sheet and Cash Flow sections (issue #195): quarterly line items × up to
 * four quarter-end dates, exactly as `services.market_data.
 * get_stock_balance_sheet`/`get_stock_cash_flow` return them — every row
 * yfinance reports, in its own order, no curated subset. One component for
 * both cards, parameterised by `title` and `fetcher`, since the two are
 * identical in shape and behaviour down to the collapsed-by-default rule
 * (a statement can run 40-65 rows, the reason it starts collapsed at all —
 * unlike InsiderPurchasesCard/InstitutionalHoldersCard, which are short
 * enough to always show).
 *
 * A plain disclosure (a button toggling `open`), not `Overlay`'s modal
 * pattern — nothing here blocks the rest of the page, so a focus trap
 * would be the wrong tool.
 */
import { memo, useState } from 'react';
import { useFetch } from '../../hooks/useFetch';
import { Loading } from '../ui/Loading';

// Balance-sheet/cash-flow cells mix dollar figures and share counts, and
// nothing here curates rows enough to know which is which (the design
// round's own call) — so this reads the cell's own shape instead of
// guessing a currency: a whole number is grouped like one ("14,687,356,000"),
// anything with a fractional part keeps up to three decimals rather than
// rounding it away.
function formatCell(value) {
  if (value === null || value === undefined) return '—';
  const abs = Math.abs(value);
  const text = Number.isInteger(value)
    ? abs.toLocaleString('en-US')
    : abs.toLocaleString('en-US', { maximumFractionDigits: 3 });
  return value < 0 ? `−${text}` : text;
}

function ChevronIcon({ open }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 150ms' }}
      aria-hidden="true"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

export const FinancialStatementCard = memo(function FinancialStatementCard({
  ticker,
  title,
  fetcher,
  emptyText,
}) {
  const [open, setOpen] = useState(false);
  const { data, loading, error, retry } = useFetch(
    (signal) => fetcher(ticker, { signal }),
    [ticker],
    { fallback: null }
  );

  const columns = data?.columns ?? [];
  const rows = data?.rows ?? [];

  return (
    <section className="bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] p-5 flex flex-col gap-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-2 bg-transparent border-none p-0 cursor-pointer text-[var(--fg-2)] w-fit"
      >
        <div className="eyebrow">{title}</div>
        <ChevronIcon open={open} />
      </button>

      {open && (
        loading ? (
          <Loading variant="skeleton" lines={4} />
        ) : error ? (
          <p className="text-[13px] text-[var(--fg-2)] m-0">
            {title} unavailable right now.{' '}
            <button
              onClick={retry}
              className="text-[var(--accent)] underline cursor-pointer bg-transparent border-none p-0 text-[13px]"
            >
              Retry
            </button>
          </p>
        ) : rows.length === 0 ? (
          <p className="text-[13px] text-[var(--fg-2)] m-0">{emptyText}</p>
        ) : (
          <div className="overflow-auto max-h-[420px] border border-[var(--border)] rounded-[var(--radius-md)]">
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-[var(--divider)]">
                  <th scope="col" className="eyebrow text-left px-3 py-2 font-normal sticky top-0 bg-[var(--bg-1)]">
                    LINE ITEM
                  </th>
                  {columns.map((c) => (
                    <th
                      key={c}
                      scope="col"
                      className="eyebrow text-right px-3 py-2 font-normal sticky top-0 bg-[var(--bg-1)]"
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.label} className="border-b border-[var(--divider)] last:border-b-0">
                    <td className="px-3 py-2 text-[13px] text-[var(--fg)] whitespace-nowrap">{row.label}</td>
                    {row.values.map((v, i) => (
                      <td
                        key={i}
                        className="px-3 py-2 text-right font-[var(--font-mono)] text-[12.5px] tabular-nums"
                        style={{ color: v !== null && v < 0 ? 'var(--negative)' : 'var(--fg)' }}
                      >
                        {formatCell(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}
    </section>
  );
});
