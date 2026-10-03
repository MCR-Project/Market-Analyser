/**
 * DeepFillDialog - the warning before a Deep-fill, its progress while it runs,
 * and what to do where it is not allowed (issue #172).
 *
 * A thin renderer: which state the fund is in, every word, and which actions
 * exist are decided by `deepFillDialog` in utils/deepFill.js (tested). A state
 * with no `start` in its actions - disabled, busy, running, ready - has no
 * Start button to render, which is how a version with Deep-fill off cannot start
 * anything from here. Goes through `Overlay` for the dialog role, Escape, the
 * focus trap and focus restoration.
 *
 * Closing it never stops a job: the job lives on the server and the chip on the
 * fund card tracks it. Only "Cancel Deep-fill" stops one, and it keeps what was
 * fetched.
 */
import { memo } from 'react';
import { Overlay } from '../ui/Overlay';
import { deepFillDialog } from '../../utils/deepFill';

/** `code` between backticks, set in monospace; everything else as written. */
function Paragraph({ text }) {
  return (
    <p className="text-sm leading-relaxed text-[var(--fg-1)] m-0">
      {text.split('`').map((part, i) => (
        i % 2 === 1
          ? <code key={i} className="font-[var(--font-mono)] text-[12px] bg-[var(--bg-3)] rounded px-1.5 py-0.5 text-[var(--fg)]">{part}</code>
          : part
      ))}
    </p>
  );
}

export const DeepFillDialog = memo(function DeepFillDialog({
  etfId, status, pending, actionError, onStart, onCancel, onClose,
}) {
  const dialog = deepFillDialog(status);
  // The state moved on under an open dialog to one with nothing to say (the
  // status went away). The page closes it; render nothing meanwhile.
  if (!dialog) return null;

  const run = { start: onStart, cancel: onCancel, close: onClose };

  return (
    <Overlay
      onClose={onClose}
      ariaLabel={`Deep-fill ${etfId}`}
      className="fixed inset-0 z-80 flex items-start justify-center pt-[12vh] px-5 pb-5"
      style={{ background: 'color-mix(in oklab, var(--bg-inset) 70%, transparent)', backdropFilter: 'blur(3px)' }}
      contentClassName="w-full max-w-[560px] max-h-[80vh] flex flex-col bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] overflow-hidden animate-[corrPop_var(--dur-fast)_var(--ease-out)]"
    >
      <div className="flex-none p-5 border-b border-[var(--divider)]">
        <div className="eyebrow mb-1">DEEP-FILL · {etfId}</div>
        <p className="text-sm text-[var(--fg-2)] m-0">Read this fund as its whole basket, not only the holdings that have prices.</p>
      </div>

      <div className="corr-scroll flex-1 min-h-0 overflow-y-auto p-5 flex flex-col gap-3.5">
        {dialog.progress && (
          <div>
            <div className="flex items-baseline justify-between gap-3 mb-2">
              <span className="text-sm font-semibold text-[var(--fg)]">{dialog.progress.phase}</span>
              <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)] tabular-nums">
                {dialog.progress.done}/{dialog.progress.total}
              </span>
            </div>
            <div
              role="progressbar"
              aria-label="Deep-fill progress"
              aria-valuemin={0}
              aria-valuemax={dialog.progress.total}
              aria-valuenow={dialog.progress.done}
              className="h-[7px] rounded-full bg-[var(--bg-3)] overflow-hidden"
            >
              <div
                className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-500"
                style={{ width: `${dialog.progress.total ? Math.round((dialog.progress.done / dialog.progress.total) * 100) : 0}%` }}
              />
            </div>
          </div>
        )}

        {dialog.body.map((text) => <Paragraph key={text} text={text} />)}

        {dialog.failures?.length > 0 && (
          <details className="text-sm text-[var(--fg-1)]">
            <summary className="cursor-pointer text-[var(--fg-2)]">Which holdings, and why</summary>
            <ul className="corr-scroll m-0 mt-2 pl-5 max-h-40 overflow-y-auto font-[var(--font-mono)] text-[11px] leading-relaxed">
              {dialog.failures.map(({ ticker, reason }) => (
                <li key={ticker}><span className="text-[var(--fg)]">{ticker}</span> — {reason}</li>
              ))}
            </ul>
          </details>
        )}

        {actionError && (
          <p role="alert" className="m-0 text-sm text-[var(--danger)]">{actionError}</p>
        )}
      </div>

      <div className="flex-none flex justify-end gap-2.5 p-4 border-t border-[var(--divider)]">
        {dialog.actions.map((action) => (
          <button
            key={action.id}
            onClick={run[action.id]}
            disabled={pending !== null && action.id !== 'close'}
            className={
              'px-4 py-2 rounded-[var(--radius-md)] text-sm cursor-pointer border transition-colors duration-150 disabled:opacity-50 disabled:cursor-wait ' +
              (action.primary
                ? 'bg-[var(--accent)] border-[var(--accent)] text-white font-semibold hover:opacity-90'
                : 'bg-transparent border-[var(--border)] text-[var(--fg-1)] hover:bg-[var(--bg-2)] hover:border-[var(--border-strong)]')
            }
          >
            {action.label}
          </button>
        ))}
      </div>
    </Overlay>
  );
});
