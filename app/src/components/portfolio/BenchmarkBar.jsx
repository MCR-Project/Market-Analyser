/**
 * BenchmarkBar — what the portfolio is being held up against.
 *
 * "Did this beat SPY" should not require creating a portfolio called SPY
 * and remembering to delete it afterwards, so a benchmark is a ticker
 * that lives in the URL and never touches the library. It is simulated
 * the same way everything else on the chart is — a basket of one — which
 * is what lets it sit in the summary table next to the portfolios without
 * any of its numbers meaning something slightly different.
 */
import { TickerSearchField } from './TickerSearchField';

export function BenchmarkBar({ benchmarks, disabled, onAdd, onRemove }) {
  return (
    <div className="flex items-start gap-3 flex-wrap mb-4">
      <div className="w-[260px]">
        <TickerSearchField
          placeholder={disabled ? 'Chart is full' : 'Compare against — SPY, QQQ…'}
          ariaLabel="Add a benchmark"
          exclude={benchmarks}
          disabled={disabled}
          onResolved={resolved => onAdd(resolved.symbol)}
        />
      </div>

      {benchmarks.length > 0 && (
        <ul className="list-none flex flex-wrap items-center gap-2 m-0 p-0 pt-1">
          {benchmarks.map(symbol => (
            <li key={symbol}>
              <span className="inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 bg-[var(--bg-2)] border border-[var(--border)] rounded-[var(--radius-pill)]">
                <span className="font-[var(--font-mono)] text-[12px] font-bold text-[var(--fg)]">{symbol}</span>
                <button
                  onClick={() => onRemove(symbol)}
                  aria-label={`Remove ${symbol} from the comparison`}
                  className="w-5 h-5 grid place-items-center bg-transparent border-none rounded-full text-[var(--fg-2)] cursor-pointer hover:text-[var(--danger)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--accent)]"
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" aria-hidden="true">
                    <path d="M18 6 6 18M6 6l12 12" />
                  </svg>
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
