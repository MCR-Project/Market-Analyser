/**
 * InstitutionalHoldersCard — top-10 institutional holders (issue #195),
 * exactly as `services.market_data.get_stock_institutional_holders`
 * ranks and limits them — always expanded, like InsiderPurchasesCard,
 * since ten rows needs no disclosure. % held is the one column the issue
 * calls out to highlight, drawn bold in the theme's accent colour.
 */
import { memo } from 'react';
import { useFetch } from '../../hooks/useFetch';
import { api } from '../../utils/api';
import { Loading } from '../ui/Loading';

// Mirrors StockFundamentalsCard's own $/B/T thresholds, so a holding's
// value reads the same way everywhere on this page.
function largeCurrency(value) {
  if (value === null || value === undefined) return '—';
  const billions = value / 1_000_000_000;
  if (billions >= 1000) return `$${(billions / 1000).toFixed(2)}T`;
  if (billions >= 1) return `$${billions.toFixed(1)}B`;
  if (billions >= 0.001) return `$${Math.round(billions * 1000)}M`;
  return `$${Math.round(value).toLocaleString('en-US')}`;
}

function percent(value) {
  if (value === null || value === undefined) return '—';
  return `${(value * 100).toFixed(2)}%`;
}

function signedPercent(value) {
  if (value === null || value === undefined) return '—';
  const text = `${Math.abs(value * 100).toFixed(2)}%`;
  return value >= 0 ? `+${text}` : `−${text}`;
}

export const InstitutionalHoldersCard = memo(function InstitutionalHoldersCard({ ticker }) {
  const { data, loading, error, retry } = useFetch(
    (signal) => api.getStockInstitutionalHolders(ticker, { signal }),
    [ticker],
    { fallback: null }
  );
  const holders = data?.holders ?? [];

  return (
    <section className="bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] p-5 flex flex-col gap-3">
      <div className="eyebrow">INSTITUTIONAL HOLDERS</div>
      {loading ? (
        <Loading variant="skeleton" lines={4} />
      ) : error ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0">
          Institutional holders unavailable right now.{' '}
          <button
            onClick={retry}
            className="text-[var(--accent)] underline cursor-pointer bg-transparent border-none p-0 text-[13px]"
          >
            Retry
          </button>
        </p>
      ) : holders.length === 0 ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0">No institutional holder data available for this ticker.</p>
      ) : (
        <div className="overflow-x-auto border border-[var(--border)] rounded-[var(--radius-md)]">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-[var(--divider)]">
                <th scope="col" className="eyebrow text-left px-3 py-2 font-normal">HOLDER</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">% HELD</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">SHARES</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">VALUE</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">CHANGE</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">REPORTED</th>
              </tr>
            </thead>
            <tbody>
              {holders.map((h, i) => (
                <tr key={`${h.holder}-${i}`} className="border-b border-[var(--divider)] last:border-b-0">
                  <td className="px-3 py-2 text-[13px] text-[var(--fg)] whitespace-nowrap">{h.holder || '—'}</td>
                  <td className="px-3 py-2 text-right font-[var(--font-mono)] text-[13px] font-bold tabular-nums text-[var(--accent)]">
                    {percent(h.pctHeld)}
                  </td>
                  <td className="px-3 py-2 text-right font-[var(--font-mono)] text-[12.5px] tabular-nums text-[var(--fg)]">
                    {h.shares != null ? Math.round(h.shares).toLocaleString('en-US') : '—'}
                  </td>
                  <td className="px-3 py-2 text-right font-[var(--font-mono)] text-[12.5px] tabular-nums text-[var(--fg)]">
                    {largeCurrency(h.value)}
                  </td>
                  <td
                    className="px-3 py-2 text-right font-[var(--font-mono)] text-[12.5px] tabular-nums"
                    style={{ color: h.pctChange != null && h.pctChange < 0 ? 'var(--negative)' : 'var(--fg)' }}
                  >
                    {signedPercent(h.pctChange)}
                  </td>
                  <td className="px-3 py-2 text-right font-[var(--font-mono)] text-[12px] text-[var(--fg-2)]">
                    {h.dateReported || '—'}
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
