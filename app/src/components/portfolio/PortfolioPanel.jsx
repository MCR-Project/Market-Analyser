/**
 * PortfolioPanel — one portfolio, and what can be done to it.
 *
 * Shows what the library knows: the name, the amount being simulated, how
 * it is rebalanced, and its composition. The composition is read-only
 * here — this is the library, and editing holdings is the holdings
 * table's job — so a portfolio with none says so plainly rather than
 * pretending to be a form that does not work yet.
 *
 * Rename is inline on the title: the name is the thing being edited, so
 * editing it in place beats a dialog that shows the same word in a box.
 * Enter or blur commits, Escape restores what was there — an empty name
 * is refused by the library rather than leaving a row with nothing to
 * click.
 */
import { useState } from 'react';

const CURRENCY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

const REBALANCE_LABELS = {
  none: 'Buy and hold',
  monthly: 'Rebalanced monthly',
  quarterly: 'Rebalanced quarterly',
  yearly: 'Rebalanced yearly',
};

const ACTION_CLASS =
  'px-3 py-1.5 text-[12.5px] font-semibold rounded-[var(--radius-md)] border cursor-pointer transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2';

function formatDate(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function Title({ portfolio, onRename }) {
  const [draft, setDraft] = useState(null);

  // Switching portfolio mid-rename would otherwise carry the draft across
  // and rename the wrong one on blur. Adjusted during render rather than
  // in an effect, as App.jsx does with its selection — see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [editingId, setEditingId] = useState(portfolio.id);
  if (editingId !== portfolio.id) {
    setEditingId(portfolio.id);
    setDraft(null);
  }

  const commit = () => {
    if (draft !== null) onRename(draft);
    setDraft(null);
  };

  if (draft === null) {
    return (
      <div className="flex items-center gap-2.5 min-w-0">
        <h1 className="text-[24px] font-extrabold text-[var(--fg)] tracking-tight m-0 truncate">
          {portfolio.name}
        </h1>
        <button
          onClick={() => setDraft(portfolio.name)}
          aria-label={`Rename ${portfolio.name}`}
          className="flex-none w-8 h-8 grid place-items-center bg-transparent border border-[var(--border)] rounded-[var(--radius-sm)] text-[var(--fg-2)] cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <input
      value={draft}
      autoFocus
      aria-label="Portfolio name"
      // Selecting on focus rather than in an effect: the name is almost
      // always being replaced, not appended to.
      onFocus={e => e.target.select()}
      onChange={e => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={e => {
        if (e.key === 'Enter') commit();
        if (e.key === 'Escape') setDraft(null);
      }}
      className="w-full max-w-[420px] px-3 h-[42px] text-[20px] font-extrabold tracking-tight text-[var(--fg)] bg-[var(--bg-1)] border border-[var(--accent-ring)] rounded-[var(--radius-md)] outline-none focus:border-[var(--accent)]"
    />
  );
}

function Fact({ label, children }) {
  return (
    <div>
      <div className="eyebrow mb-1">{label}</div>
      <div className="text-[14px] text-[var(--fg)] font-semibold">{children}</div>
    </div>
  );
}

export function PortfolioPanel({ portfolio, onRename, onDuplicate, onDelete }) {
  const holdings = portfolio.holdings || [];

  return (
    <div className="max-w-[720px]">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-6">
        <Title portfolio={portfolio} onRename={onRename} />
        <div className="flex items-center gap-2 flex-none">
          <button
            onClick={onDuplicate}
            className={`${ACTION_CLASS} text-[var(--fg-1)] bg-[var(--bg-2)] border-[var(--border)] hover:bg-[var(--bg-3)] focus-visible:outline-[var(--accent)]`}
          >
            Duplicate
          </button>
          <button
            onClick={onDelete}
            className={`${ACTION_CLASS} text-[var(--danger)] bg-[var(--danger-soft)] border-[var(--danger-ring)] hover:bg-[var(--danger-ring)] focus-visible:outline-[var(--danger)]`}
          >
            Delete
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-5 p-5 mb-6 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)]">
        <Fact label="AMOUNT">{CURRENCY.format(portfolio.value)}</Fact>
        <Fact label="HOLDINGS">{holdings.length}</Fact>
        <Fact label="METHOD">{REBALANCE_LABELS[portfolio.rebalance] || REBALANCE_LABELS.none}</Fact>
        <Fact label="CREATED">{formatDate(portfolio.createdAt)}</Fact>
      </div>

      <div className="eyebrow mb-2">COMPOSITION</div>
      {holdings.length === 0 ? (
        <p className="text-[13.5px] text-[var(--fg-2)] leading-relaxed m-0">
          This portfolio has no holdings yet.
        </p>
      ) : (
        <ul className="list-none m-0 p-0 border border-[var(--border)] rounded-[var(--radius-md)] overflow-hidden">
          {holdings.map(holding => (
            <li
              key={holding.ticker}
              className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--divider)] last:border-b-0"
            >
              <span className="font-[var(--font-mono)] text-[13px] font-bold text-[var(--fg)]">
                {holding.ticker}
              </span>
              <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg-1)]">
                {holding.weight}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
