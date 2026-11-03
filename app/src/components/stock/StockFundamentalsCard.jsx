/**
 * StockFundamentalsCard — trailing/forward P/E, profit margin, held %
 * insiders/institutions, earnings quarterly growth, total debt and revenue
 * per share for the open stock (issue #194).
 *
 * Its own fetch (`api.getStockFundamentals`), not a field read off the
 * already-fetched `info`/`metrics` this page holds: these eight are always
 * a live yfinance call with no database path
 * (`services.market_data.get_stock_fundamentals`'s own docstring), the same
 * reason the About card below fetches its description separately rather
 * than folding it into the header's `info` request — a Yahoo hiccup here
 * must not blank out a card that already loaded successfully.
 *
 * Deliberately not read through the measurement system
 * (`backend/measurements/`) the way the holdings table's own P/E Ratio /
 * Ownership / ... columns are: that system is scoped to a fund's `etf_id`
 * and its holdings table, and this page has neither when the open ticker
 * isn't held by any tracked fund. Same underlying
 * `services.market_data.get_stock_fundamentals` either way, just a
 * different route and a different presentation (`Stat` tiles here, MDX
 * cells there) — the same split `StockMetricsCard` already draws against
 * `backend/portfolio_metrics/`.
 */
import { memo } from 'react';
import { useFetch } from '../../hooks/useFetch';
import { api } from '../../utils/api';
import { Loading } from '../ui/Loading';

function percent(value, { signed = false } = {}) {
  if (value === null || value === undefined) return '—';
  const text = `${(Math.abs(value) * 100).toFixed(1)}%`;
  if (!signed) return text;
  return `${value >= 0 ? '+' : '−'}${text}`;
}

function ratio(value) {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(1)}x`;
}

function currencyPerShare(value) {
  if (value === null || value === undefined) return '—';
  return `$${value.toFixed(2)}`;
}

// Mirrors market_cap.py's / total_debt.py's own $/B/T thresholds, so this
// card reads a dollar amount exactly the way the holdings table does.
function largeCurrency(value) {
  if (value === null || value === undefined) return '—';
  const billions = value / 1_000_000_000;
  if (billions >= 1000) return `$${(billions / 1000).toFixed(2)}T`;
  if (billions >= 1) return `$${billions.toFixed(1)}B`;
  return `$${Math.round(billions * 1000)}M`;
}

function tone(value) {
  if (value === null || value === undefined) return 'var(--fg)';
  if (value > 0) return 'var(--success)';
  if (value < 0) return 'var(--danger)';
  return 'var(--fg)';
}

const FIELDS = [
  { key: 'trailingPE', label: 'TRAILING P/E', format: ratio },
  { key: 'forwardPE', label: 'FORWARD P/E', format: ratio },
  { key: 'profitMargins', label: 'PROFIT MARGIN', format: (v) => percent(v, { signed: true }), toned: true },
  { key: 'earningsQuarterlyGrowth', label: 'EARNINGS GROWTH', format: (v) => percent(v, { signed: true }), toned: true },
  { key: 'heldPercentInsiders', label: '% INSIDERS', format: percent },
  { key: 'heldPercentInstitutions', label: '% INSTITUTIONS', format: percent },
  { key: 'totalDebt', label: 'TOTAL DEBT', format: largeCurrency },
  { key: 'revenuePerShare', label: 'REVENUE/SHARE', format: currencyPerShare },
];

function Stat({ label, value }) {
  return (
    <div>
      <div className="eyebrow mb-1">{label}</div>
      <div
        className="text-[15px] font-extrabold tabular-nums tracking-tight"
        style={{ color: value.tone || 'var(--fg)' }}
      >
        {value.text}
      </div>
    </div>
  );
}

export const StockFundamentalsCard = memo(function StockFundamentalsCard({ ticker }) {
  const { data, loading, error, retry } = useFetch(
    (signal) => api.getStockFundamentals(ticker, { signal }),
    [ticker],
    { fallback: null }
  );

  return (
    <section className="bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] p-5 flex flex-col gap-4">
      <div className="eyebrow">FUNDAMENTALS</div>
      {loading ? (
        <Loading variant="skeleton" lines={2} />
      ) : error ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0">
          Fundamentals unavailable right now.{' '}
          <button
            onClick={retry}
            className="text-[var(--accent)] underline cursor-pointer bg-transparent border-none p-0 text-[13px]"
          >
            Retry
          </button>
        </p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          {FIELDS.map(({ key, label, format, toned }) => {
            const raw = data?.[key] ?? null;
            return (
              <Stat
                key={key}
                label={label}
                value={{ text: format(raw), tone: toned ? tone(raw) : undefined }}
              />
            );
          })}
        </div>
      )}
    </section>
  );
});
