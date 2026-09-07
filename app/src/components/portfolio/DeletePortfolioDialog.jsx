/**
 * DeletePortfolioDialog — the confirmation in front of a delete.
 *
 * Names the portfolio being deleted rather than asking "are you sure?"
 * about nothing in particular: with a list of similarly-named portfolios,
 * the name is the only thing that makes the answer meaningful. Deleting
 * is not undoable — the library is this browser's storage and there is no
 * server copy to restore from — so the wording says that too.
 *
 * Keyboard behaviour (Escape, focus trap, focus returned to whatever
 * opened it) comes from Overlay, to the standard set in #24.
 */
import { Overlay } from '../ui/Overlay';

export function DeletePortfolioDialog({ portfolio, onConfirm, onCancel }) {
  return (
    <Overlay
      onClose={onCancel}
      ariaLabel={`Delete ${portfolio.name}`}
      className="fixed inset-0 z-80 flex items-start justify-center pt-[18vh] px-5 pb-5"
      style={{ background: 'color-mix(in oklab, var(--bg-inset) 70%, transparent)', backdropFilter: 'blur(3px)' }}
      contentClassName="w-full max-w-[420px] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] p-5 animate-[corrPop_var(--dur-fast)_var(--ease-out)]"
    >
      <div className="eyebrow mb-2">DELETE PORTFOLIO</div>
      <p className="text-[14px] text-[var(--fg)] m-0 mb-1.5 leading-relaxed">
        Delete “<strong className="font-bold">{portfolio.name}</strong>”?
      </p>
      <p className="text-[13px] text-[var(--fg-2)] m-0 mb-4 leading-relaxed">
        It is stored in this browser only, so this cannot be undone.
      </p>
      <div className="flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="px-3.5 py-2 text-[13px] font-semibold text-[var(--fg-1)] bg-[var(--bg-2)] border border-[var(--border)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-3)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          Keep it
        </button>
        <button
          onClick={onConfirm}
          className="px-3.5 py-2 text-[13px] font-semibold text-[var(--danger)] bg-[var(--danger-soft)] border border-[var(--danger-ring)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--danger-ring)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--danger)]"
        >
          Delete
        </button>
      </div>
    </Overlay>
  );
}
