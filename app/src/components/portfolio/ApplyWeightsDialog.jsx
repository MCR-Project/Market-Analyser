/**
 * ApplyWeightsDialog — the confirmation in front of applying weight edits.
 *
 * It shows what is about to change rather than asking "are you sure?"
 * about nothing in particular: a table of weights all looks alike, and by
 * the time several have been retyped it is easy to have moved one that
 * was not meant to move. Old → new for each row, and the total before and
 * after, is the whole of what is being decided.
 *
 * Keyboard behaviour (Escape, focus trap, focus returned to whatever
 * opened it) comes from Overlay, to the standard set in #24.
 */
import { Overlay } from '../ui/Overlay';

/** Enough rows to see the shape of the change; past this the list is
 *  scenery rather than information, and the totals carry the meaning. */
const LISTED = 8;

export function ApplyWeightsDialog({ changes, totalBefore, totalAfter, onConfirm, onCancel }) {
  const shown = changes.slice(0, LISTED);
  const hidden = changes.length - shown.length;

  return (
    <Overlay
      onClose={onCancel}
      ariaLabel="Apply weight changes"
      className="fixed inset-0 z-80 flex items-start justify-center pt-[14vh] px-5 pb-5"
      style={{ background: 'color-mix(in oklab, var(--bg-inset) 70%, transparent)', backdropFilter: 'blur(3px)' }}
      contentClassName="w-full max-w-[460px] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] p-5 animate-[corrPop_var(--dur-fast)_var(--ease-out)]"
    >
      <div className="eyebrow mb-2">APPLY WEIGHTS</div>
      <p className="text-[13.5px] text-[var(--fg-1)] leading-relaxed m-0 mb-3">
        {changes.length === 1
          ? 'One weight has changed. Applying it saves the portfolio and runs the simulation again.'
          : `${changes.length} weights have changed. Applying them saves the portfolio and runs the simulation again.`}
      </p>

      <ul className="list-none m-0 mb-3 p-0 border border-[var(--border)] rounded-[var(--radius-md)] overflow-hidden">
        {shown.map(change => (
          <li
            key={change.ticker}
            className="flex items-center justify-between gap-3 px-3 py-2 border-b border-[var(--divider)] last:border-b-0"
          >
            <span className="font-[var(--font-mono)] text-[12.5px] font-bold text-[var(--fg)]">
              {change.ticker}
            </span>
            <span className="font-[var(--font-mono)] text-[12.5px] text-[var(--fg-2)]">
              {change.from}% <span aria-hidden="true">→</span>{' '}
              <span className="text-[var(--fg)] font-bold">{change.to}%</span>
            </span>
          </li>
        ))}
        {hidden > 0 && (
          <li className="px-3 py-2 text-[12px] text-[var(--fg-2)]">
            and {hidden} more
          </li>
        )}
      </ul>

      <p className="text-[12.5px] text-[var(--fg-2)] leading-relaxed m-0 mb-4">
        Allocated in total: <span className="font-[var(--font-mono)]">{totalBefore}%</span>{' '}
        <span aria-hidden="true">→</span>{' '}
        <span className="font-[var(--font-mono)] text-[var(--fg-1)] font-bold">{totalAfter}%</span>
        {totalAfter > 100 ? ' — the simulation scales these down to 100%.' : ''}
      </p>

      <div className="flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="px-3.5 py-2 text-[13px] font-semibold text-[var(--fg-1)] bg-[var(--bg-2)] border border-[var(--border)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-3)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          Keep editing
        </button>
        <button
          onClick={onConfirm}
          className="px-3.5 py-2 text-[13px] font-semibold text-[var(--success)] bg-[var(--success-soft)] border border-[var(--success-ring)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--success-ring)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--success)]"
        >
          Apply and recompute
        </button>
      </div>
    </Overlay>
  );
}
