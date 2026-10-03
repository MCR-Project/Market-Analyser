/**
 * DeepFillControl - the Deep-fill's presence on the fund card (issue #172).
 *
 * One line, whose content is `deepFillControl(status)`'s state (utils/deepFill.js):
 * nothing for a fund with no Untracked holdings; a "Deep-fill" button for one
 * that has them, which opens the dialog (also where a version with Deep-fill off
 * says why, so it is shown there too); a "Deep-filling 212/457" chip while a job
 * runs; and the "Full fund as of ..." note, in place of the button, until the
 * result expires. Every state but nothing opens the same dialog - the chip and
 * the note are how to get back to it after closing it.
 */
import { memo } from 'react';
import { deepFillControl, chipLabel, readyNote, controlCaption } from '../../utils/deepFill';

const BASE = 'flex-none flex items-center gap-1.5 font-[var(--font-mono)] text-[11px] rounded-full px-2.5 py-1 cursor-pointer border transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]';

export const DeepFillControl = memo(function DeepFillControl({ status, onOpen }) {
  const control = deepFillControl(status);
  if (control.kind === 'hidden') return null;

  if (control.kind === 'running') {
    return (
      <button onClick={onOpen} className={`${BASE} bg-[var(--accent-soft)] border-[var(--accent-ring)] text-[var(--accent)] font-semibold tabular-nums`}>
        <span className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse" aria-hidden="true" />
        {chipLabel(status)}
      </button>
    );
  }

  if (control.kind === 'ready') {
    return (
      <button onClick={onOpen} title="Details of this Deep-fill" className={`${BASE} bg-[var(--success-soft)] border-[var(--success-ring)] text-[var(--success)]`}>
        <span aria-hidden="true">●</span>
        {readyNote(status)}
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2.5 flex-wrap">
      <button onClick={onOpen} className={`${BASE} bg-transparent border-[var(--accent-ring)] text-[var(--accent)] hover:bg-[var(--accent-soft)]`}>
        {control.kind === 'resume' ? 'Resume Deep-fill' : 'Deep-fill'}
      </button>
      <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-3)]">{controlCaption(status)}</span>
    </div>
  );
});
