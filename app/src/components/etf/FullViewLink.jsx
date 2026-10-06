/**
 * FullViewLink — the way into a deep-filled fund's Full view (issue #173): shown on
 * the Matrix and Network tabs, and only while the fund is deep-filled (the callers
 * check `etf.deepFill`, which the backend adds only then). It opens in a tab of its
 * own because the picture is a page, not a panel — every holding, filling the window
 * — and because the tab the person came from keeps its place.
 */
import { memo } from 'react';
import { Link } from 'react-router';
import { fullViewPath } from '../../utils/fullViewRoute';

export const FullViewLink = memo(function FullViewLink({ etfId, kind }) {
  return (
    <Link
      to={fullViewPath(etfId, kind)}
      target="_blank"
      rel="noopener"
      title={`Every holding of ${etfId}, zoomable, in a page of its own`}
      className="ml-auto flex-none flex items-center gap-1.5 font-[var(--font-mono)] text-xs font-semibold text-[var(--accent)] no-underline bg-transparent border border-[var(--accent-ring)] rounded-full px-3 py-1.5 transition-colors duration-150 hover:bg-[var(--accent-soft)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
    >
      Full view
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M7 17 17 7" /><path d="M8 7h9v9" />
      </svg>
    </Link>
  );
});
