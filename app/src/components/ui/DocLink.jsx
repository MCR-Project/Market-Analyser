/**
 * DocLink — the small "?" that opens a measurement's documentation.
 *
 * Placed wherever a measurement is named but not explained: the table's
 * column headers, and the rows of the measurement picker. Those are the
 * two moments someone is actually looking at a number they don't
 * recognise, which is where the answer should be.
 *
 * Always a sibling of whatever it sits next to, never nested inside it —
 * the column header is a sort button and the picker row is a toggle
 * button, and an anchor inside a button is both invalid HTML and a
 * guaranteed way to sort a column you meant to read about. The click is
 * stopped from propagating for the same reason.
 */
import { memo } from 'react';
import { Link } from 'react-router';

export const DocLink = memo(function DocLink({ measurementId, measurementName, className = '' }) {
  return (
    <Link
      to={`/docs/${measurementId}`}
      onClick={e => e.stopPropagation()}
      aria-label={`Documentation for ${measurementName}`}
      title={`Documentation for ${measurementName}`}
      className={`flex-none grid place-items-center w-[15px] h-[15px] rounded-full no-underline font-[var(--font-mono)] text-[9px] font-bold leading-none border border-[var(--border-strong)] text-[var(--fg-3)] transition-colors duration-150 hover:text-[var(--accent)] hover:border-[var(--accent-ring)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] ${className}`}
    >
      ?
    </Link>
  );
});
