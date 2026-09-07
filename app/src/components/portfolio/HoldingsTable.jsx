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
 * **Weights are edited, then applied.** Typing into a weight changes
 * nothing but the box it is typed into: it does not save the portfolio,
 * and it does not re-run the simulation. Weights are worked out by
 * comparison — this one up, that one down, does the total still make
 * sense — and a table that re-simulates as each digit lands spends its
 * time answering half-written questions. **Recompute** applies the whole
 * set at once, so one deliberate decision costs one run.
 *
 * Everything on screen still reacts immediately: the running total, the
 * over-100 card and Normalize all read the numbers being typed, because
 * those are arithmetic and cost nothing. Only the simulated columns wait,
 * and they stay honest about it by describing the weights that were
 * actually applied.
 *
 * Weights are ratios, not a budget. Any non-negative numbers describe the
 * basket by their proportions, and the simulation normalises them, so a
 * total under 100 is simply scaled up rather than treated as cash. A
 * total *over* 100 is worth saying out loud — it usually means someone
 * expected the numbers to be a percentage of the money and is about to be
 * surprised — so the card explains it rather than the input refusing it.
 * **Normalize** rewrites the weights to what the simulation is doing with
 * them anyway, as another pending edit rather than behind anyone's back.
 *
 * Negative weights are the one thing refused outright: shorting is not
 * modelled, and coercing -5 to 5 or to 0 would both be inventing an
 * intention nobody expressed.
 */
import { memo, useState } from 'react';
import { normaliseWeights, totalWeight } from '../../utils/weights';
import { ApplyWeightsDialog } from './ApplyWeightsDialog';

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
  portfolioId,
  holdings,
  simulation,
  stale,
  onChange,
  // Rendered at the head of the section rather than after the rows: on a
  // portfolio of any size the bottom of the table is a scroll away, and
  // adding a holding is the one action here that has nothing to do with
  // the row you happen to be looking at.
  addControl,
}) {
  // The weights as they are being typed: ticker → raw text, because "1",
  // "" and "12." are all legitimate mid-edit states that are not numbers
  // yet. A ticker absent from here is showing its applied weight.
  const [drafts, setDrafts] = useState({});
  const [refused, setRefused] = useState(null);
  const [confirming, setConfirming] = useState(false);

  // Switching portfolio with edits in flight would otherwise apply one
  // portfolio's weights to another. Adjusted during render rather than in
  // an effect, as App.jsx does with its selection — see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [editingId, setEditingId] = useState(portfolioId);
  if (editingId !== portfolioId) {
    setEditingId(portfolioId);
    setDrafts({});
    setRefused(null);
    setConfirming(false);
  }

  // The basket as typed. Text that is not a usable number leaves that
  // holding at its applied weight, so the total never reads as though a
  // half-typed row were zero.
  const edited = holdings.map(holding => {
    const raw = drafts[holding.ticker];
    if (raw === undefined) return holding;
    const value = Number(raw);
    if (raw.trim() === '' || !Number.isFinite(value) || value < 0) return holding;
    return { ...holding, weight: value };
  });

  const changes = edited
    .map((holding, i) => ({ ticker: holding.ticker, from: holdings[i].weight, to: holding.weight }))
    .filter(change => change.from !== change.to);

  const total = totalWeight(edited);
  const appliedTotal = totalWeight(holdings);
  const over = total > 100 + TOLERANCE;
  const balanced = Math.abs(total - 100) <= TOLERANCE;

  const byTicker = new Map((simulation?.holdings || []).map(h => [h.ticker, h]));
  const windowStart = simulation?.start || null;

  const setWeight = (ticker, text) => {
    setDrafts(current => ({ ...current, [ticker]: text }));
    const value = Number(text);
    if (text.trim() !== '' && Number.isFinite(value) && value < 0) {
      setRefused('Weights cannot be negative — shorting is not modelled.');
    } else {
      setRefused(null);
    }
  };

  const revert = (ticker) => {
    setDrafts(current => {
      const next = { ...current };
      delete next[ticker];
      return next;
    });
    setRefused(null);
  };

  // Normalize is an edit like any other: it fills the boxes with what the
  // simulation would do to these weights anyway, and waits to be applied.
  const normalize = () => {
    const normalised = normaliseWeights(edited);
    setDrafts(Object.fromEntries(normalised.map(h => [h.ticker, String(h.weight)])));
    setRefused(null);
  };

  const apply = () => {
    onChange(edited);
    setDrafts({});
    setRefused(null);
    setConfirming(false);
  };

  // Removing a holding is not a weight edit — it changes what the
  // portfolio is, and applies at once. Pending weights survive it.
  const remove = (ticker) => {
    revert(ticker);
    onChange(holdings.filter(h => h.ticker !== ticker));
  };

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
            onClick={normalize}
            disabled={holdings.length === 0 || total <= 0 || balanced}
            className="px-2.5 py-1 text-[12px] font-semibold text-[var(--fg-1)] bg-[var(--bg-2)] border border-[var(--border)] rounded-[var(--radius-sm)] cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-3)] disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
          >
            Normalize
          </button>
          <button
            onClick={() => setConfirming(true)}
            disabled={changes.length === 0}
            title={
              changes.length === 0
                ? 'No weight changes to apply'
                : 'Save these weights and run the simulation again'
            }
            className="px-2.5 py-1 text-[12px] font-semibold text-[var(--success)] bg-[var(--success-soft)] border border-[var(--success-ring)] rounded-[var(--radius-sm)] cursor-pointer transition-colors duration-150 hover:bg-[var(--success-ring)] disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--success)]"
          >
            Recompute
            {changes.length > 0 && ` (${changes.length})`}
          </button>
        </div>
      </div>

      {addControl}

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
          <table className="w-full border-collapse">
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
              {holdings.map((holding, i) => {
                const run = byTicker.get(holding.ticker);
                const late = run && windowStart && run.firstDate && run.firstDate > windowStart;
                const never = run && !run.firstDate;
                const pending = edited[i].weight !== holding.weight;
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
                          onKeyDown={e => {
                            // Escape puts this row back to the weight the
                            // simulation actually used.
                            if (e.key === 'Escape') revert(holding.ticker);
                            if (e.key === 'Enter' && changes.length > 0) setConfirming(true);
                          }}
                          aria-label={`Weight of ${holding.ticker}, percent`}
                          className="w-[68px] h-[28px] px-2 text-right bg-[var(--bg-1)] border rounded-[var(--radius-sm)] font-[var(--font-mono)] text-[12.5px] text-[var(--fg)] outline-none focus:border-[var(--accent-ring)]"
                          style={{ borderColor: pending ? 'var(--success-ring)' : 'var(--border)' }}
                        />
                        <span className="text-[var(--fg-2)]">%</span>
                      </span>
                    </Cell>
                    {/* The simulated columns describe the applied weights,
                        so they dim while a run is in flight rather than
                        while somebody is still typing. */}
                    <Cell className="text-[var(--fg-1)]" >
                      <span style={{ opacity: stale ? 0.5 : 1 }}>
                        {run ? CURRENCY.format(run.finalValue) : '—'}
                      </span>
                    </Cell>
                    <Cell>
                      <span style={{ color: toneOf(run?.return), opacity: stale ? 0.5 : 1 }}>
                        {run ? signed(run.return, v => `${v.toFixed(1)}%`) : '—'}
                      </span>
                    </Cell>
                    <Cell>
                      <span style={{ color: toneOf(run?.contribution), opacity: stale ? 0.5 : 1 }}>
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

      {changes.length > 0 && (
        <p className="text-[12px] text-[var(--fg-2)] leading-relaxed m-0 mt-2">
          {changes.length === 1 ? 'One weight has' : `${changes.length} weights have`} changed.
          The columns above still describe the weights last applied — Recompute to run these.
        </p>
      )}

      {confirming && (
        <ApplyWeightsDialog
          changes={changes}
          totalBefore={appliedTotal}
          totalAfter={total}
          onConfirm={apply}
          onCancel={() => setConfirming(false)}
        />
      )}
    </div>
  );
});
