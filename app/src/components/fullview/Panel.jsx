/**
 * Panel — the box a Full view drawing sits in (issue #173): the full width of the
 * page and exactly as tall as it is wide, with nothing in it but the drawing. The page
 * scrolls to reach the rest, rather than squeezing a square into whatever height is
 * left under the header. The legend and the controls are outside it.
 *
 * Sized by the page's width alone (`aspect-square`), never by what is drawn, so a
 * canvas drawn at the box's measured size cannot grow the box it was measured from.
 * `ref` is a plain prop (React 19), so `useElementSize`'s callback ref attaches here.
 */
export function Panel({ ref, className = '', children }) {
  return (
    <div
      ref={ref}
      className={`relative w-full aspect-square bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] overflow-hidden ${className}`}
    >
      {children}
    </div>
  );
}
