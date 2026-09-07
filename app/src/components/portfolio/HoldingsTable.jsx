/**
 * HoldingsTable — the portfolio's composition, and the only place it is
 * edited.
 *
 * Each row is a ticker, the share of the money it takes, and what the
 * simulation made of it: what it ended up worth, what it returned on its
 * own, and how many dollars of the portfolio's gain came from it. The
 * last of those is not the row's final value — once a rebalance moves
 * money between holdings, a final value says nothing about which holding
 * earned it (see backend/services/portfolio.py).
 *
 * Weights are ratios, not a budget. Any non-negative numbers describe the
 * basket by their proportions, and the simulation normalises them, so a
 * total under 100 is simply scaled up rather than treated as cash. A
 * total *over* 100 is worth saying out loud — it usually means someone
 * expected the numbers to be a percentage of the money and is about to be
 * surprised — so the card explains it rather than the input refusing it.
 * **Normalize** rewrites the weights to what the simulation is doing with
 * them anyway.
 *
 * Negative weights are the one thing refused outright: shorting is not
 * modelled, and coercing -5 to 5 or to 0 would both be inventing an
 * intention nobody expressed.
 */
import { memo, useState } from 'react';
import { normaliseWeights, totalWeight } from '../../utils/weights';

const CURRENCY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

/** A total this close to 100 is 100 — a hundredth adrift after rounding
 *  is not something to warn anybody about. */
const TOLERANCE = 0.05;

function signed(value, format) {
  if (value === null || value === undefined) return '—';
  const text = format(Math.abs(value));
  return `${value >= 0 ? '+' : '−'}${text}`;
}

function toneOf(value) {
  if (value === null || value === undefined) return 'var(--fg-2)';
  if (value > 0) return 'var(--success)';
  if (value < 0) return 'var(--danger)';
  return 'var(--fg-1)';
}

function Cell({ children, className = '' }) {
  return (
    <td className={`px-3 py-2.5 font-[var(--font-mono)] text-[12.5px] text-right whitespace-nowrap ${className}`}>
      {children}
    </td>
  );
}

export const HoldingsTable = memo(function HoldingsTable({
  holdings,
  simulation,
  stale,
  onChange,
}) {
  // The text being typed, which is not yet a number: "1", "" and "12." are
  // all legitimate mid-edit states that must not be parsed and written
  // back, or the field fights whoever is typing into it.
  const [drafts, setDrafts] = useState({});
  const [refused, setRefused] = useState(null);

  const total = totalWeight(holdings);
  const over = total > 100 + TOLERANCE;
  const balanced = Math.abs(total - 100) <= TOLERANCE;

  const byTicker = new Map((simulation?.holdings || []).map(h => [h.ticker, h]));
  const windowStart = simulation?.start || null;

  const setWeight = (ticker, text) => {
    setDrafts(d => ({ ...d, [ticker]: text }));
    if (text.trim() === '') return;
    const value = Number(text);
    if (!Number.isFinite(value)) return;
    if (value < 0) {
      setRefused('Weights cannot be negative — shorting is not modelled.');
      return;
    }
    setRefused(null);
    onChange(holdings.map(h => (h.ticker === ticker ? { ...h, weight: value } : h)));
  };

  const commit = (ticker) => {
    setDrafts(current => {
      const next = { ...current };
      delete next[ticker];
      return next;
    });
    setRefused(null);
  };

  const remove = (ticker) => onChange(holdings.filter(h => h.ticker !== ticker));

  return (
    <div>
      <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
        <div className="eyebrow">COMPOSITION</div>
        <div className="flex items-center gap-2.5">
          <span
            className="font-[var(--font-mono)] text-[12px]"
            style={{ color: over ? 'var(--warning)' : balanced ? 'var(--fg-2)' : 'var(--fg-1)' }}
          >
            {total}% allocated
          </span>
          <button
            onClick={() => onChange(normaliseWeights(holdings))}
            disabled={holdings.length === 0 || total <= 0 || balanced}
            className="px-2.5 py-1 text-[12px] font-semibold text-[var(--fg-1)] bg-[var(--bg-2)] border border-[var(--border)] rounded-[var(--radius-sm)] cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-3)] disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
          >
            Normalize
          </button>
        </div>
      </div>

      {over && (
        <div
          role="status"
          className="flex items-start gap-3 p-3 mb-3 rounded-[var(--radius-md)] border"
          style={{ background: 'var(--warning-soft)', borderColor: 'var(--warning-ring)' }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--warning)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-none mt-0.5" aria-hidden="true">
            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" />
          </svg>
          <p className="text-[12.5px] text-[var(--fg-1)] leading-relaxed m-0">
            These weights add up to {total}%. They are ratios rather than a
            budget, so the simulation scales them down to 100% and runs the
            portfolio you would expect — <strong className="font-bold">Normalize</strong> writes
            those scaled weights back here, if you would rather read them
            that way.
          </p>
        </div>
      )}

      {refused && (
        <p role="alert" className="text-[12.5px] text-[var(--danger)] leading-relaxed m-0 mb-2">
          {refused}
        </p>
      )}

      {holdings.length === 0 ? (
        <p className="text-[13.5px] text-[var(--fg-2)] leading-relaxed m-0">
          This portfolio has no holdings yet.
        </p>
      ) : (
        <div className="overflow-x-auto border border-[var(--border)] rounded-[var(--radius-md)]">
          <table className="w-full border-collapse" style={{ opacity: stale ? 0.55 : 1, transition: 'opacity 120ms' }}>
            <thead>
              <tr className="border-b border-[var(--divider)]">
                <th scope="col" className="eyebrow text-left px-3 py-2 font-normal">TICKER</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">WEIGHT</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">VALUE</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">RETURN</th>
                <th scope="col" className="eyebrow text-right px-3 py-2 font-normal">CONTRIBUTION</th>
                <th scope="col" className="px-3 py-2"><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody>
              {holdings.map(holding => {
                const run = byTicker.get(holding.ticker);
                const late = run && windowStart && run.firstDate && run.firstDate > windowStart;
                const never = run && !run.firstDate;
                return (
                  <tr key={holding.ticker} className="border-b border-[var(--divider)] last:border-b-0">
                    <td className="px-3 py-2.5">
                      <span className="font-[var(--font-mono)] text-[13px] font-bold text-[var(--fg)]">
                        {holding.ticker}
                      </span>
                      {(late || never) && (
                        <span
                          className="block text-[11px] text-[var(--warning)] leading-snug mt-0.5"
                          title="An allocation waits in cash until its holding has a price"
                        >
                          {never
                            ? 'no prices in this window — held as cash'
                            : `cash until ${run.firstDate}`}
                        </span>
                      )}
                    </td>
                    <Cell>
                      <span className="inline-flex items-center gap-1">
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          inputMode="decimal"
                          value={drafts[holding.ticker] ?? holding.weight}
                          onChange={e => setWeight(holding.ticker, e.target.value)}
                          onBlur={() => commit(holding.ticker)}
                          onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }}
                          aria-label={`Weight of ${holding.ticker}, percent`}
                          className="w-[68px] h-[28px] px-2 text-right bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-sm)] font-[var(--font-mono)] text-[12.5px] text-[var(--fg)] outline-none focus:border-[var(--accent-ring)]"
                        />
                        <span className="text-[var(--fg-2)]">%</span>
                      </span>
                    </Cell>
                    <Cell className="text-[var(--fg-1)]">
                      {run ? CURRENCY.format(run.finalValue) : '—'}
                    </Cell>
                    <Cell>
                      <span style={{ color: toneOf(run?.return) }}>
                        {run ? signed(run.return, v => `${v.toFixed(1)}%`) : '—'}
                      </span>
                    </Cell>
                    <Cell>
                      <span style={{ color: toneOf(run?.contribution) }}>
                        {run ? signed(run.contribution, v => CURRENCY.format(v)) : '—'}
                      </span>
                    </Cell>
                    <td className="px-3 py-2.5 text-right">
                      <button
                        onClick={() => remove(holding.ticker)}
                        aria-label={`Remove ${holding.ticker}`}
                        className="w-7 h-7 grid place-items-center bg-transparent border border-[var(--border)] rounded-[var(--radius-sm)] text-[var(--fg-2)] cursor-pointer transition-colors duration-150 hover:text-[var(--danger)] hover:border-[var(--danger-ring)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--danger)]"
                      >
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
                          <path d="M18 6 6 18M6 6l12 12" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
});
