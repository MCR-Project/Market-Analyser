/**
 * StorageNotice — what to say when the browser's storage let us down.
 *
 * Three failures the page must never hide, because in each of them the
 * app looks like it is working while quietly not keeping anything:
 *
 *  - storage unreachable (a private window, blocked site data): the
 *    session works, nothing survives the tab closing
 *  - unreadable contents: something was there, none of it was portfolios,
 *    and the library therefore starts empty through no fault of the
 *    person looking at it
 *  - no room left: the last change is on screen but not on disk
 *
 * Each says what happened and what still works, rather than an apology.
 */
import { memo } from 'react';
import { STORAGE_CORRUPT, STORAGE_FULL, STORAGE_UNAVAILABLE } from '../../store/portfolioStorage';

const NOTICES = {
  [STORAGE_UNAVAILABLE]: {
    tone: 'warning',
    title: 'Portfolios cannot be saved in this browser',
    message:
      'Site data is unavailable here — usually a private window, or storage blocked for this site. You can still build a portfolio and simulate it; it will be gone when the tab closes.',
  },
  [STORAGE_CORRUPT]: {
    tone: 'warning',
    title: 'Saved portfolios could not be read',
    message:
      'What this browser had stored was not readable as portfolios, so the library started empty. Anything created from here is saved normally.',
  },
  [STORAGE_FULL]: {
    tone: 'danger',
    title: 'The last change was not saved',
    message:
      'This browser’s storage is full. The change is still on screen, but it will not survive a reload until there is room — deleting a portfolio you no longer need is usually enough.',
  },
};

export const StorageNotice = memo(function StorageNotice({ status }) {
  const notice = NOTICES[status];
  if (!notice) return null;

  const accent = notice.tone === 'danger' ? 'var(--danger)' : 'var(--warning)';
  const soft = notice.tone === 'danger' ? 'var(--danger-soft)' : 'var(--warning-soft)';
  const ring = notice.tone === 'danger' ? 'var(--danger-ring)' : 'var(--warning-ring)';

  return (
    <div
      role="status"
      className="flex items-start gap-3 p-3.5 mb-6 rounded-[var(--radius-md)] border"
      style={{ background: soft, borderColor: ring }}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={accent} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" className="flex-none mt-0.5" aria-hidden="true">
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
        <path d="M12 9v4" /><path d="M12 17h.01" />
      </svg>
      <div className="min-w-0">
        <div className="text-[13.5px] font-bold text-[var(--fg)]">{notice.title}</div>
        <p className="text-[13px] text-[var(--fg-1)] leading-relaxed m-0 mt-1">{notice.message}</p>
      </div>
    </div>
  );
});
