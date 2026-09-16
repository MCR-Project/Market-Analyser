/**
 * CostBadge — how expensive a measurement is to compute, right where a
 * reader is choosing or looking at one (issue #115).
 *
 * Reads `{ score, rating }` straight off a manifest row or a live run
 * response (`GET /api/measurements`, `GET /api/measurements/<route>` —
 * both carry `cost`, see `backend/measurements/registry.py`) and draws
 * one of four labels — Short, Medium, Long, Extremely long — never
 * computing anything itself. The rating is derived entirely server-side
 * from what a plugin declares (`measurements/cost.py`); this component's
 * only job is to make that visible, the same "no format-specific logic
 * on this side" rule the whole cell-rendering system already follows.
 *
 * Informational only (issue #115's own scope) — nothing here gates,
 * warns, or defers anything, so the colour scale stays restrained rather
 * than alarming: Short and Medium read as neutral, and only Long/
 * Extremely long borrow the warning/danger tokens, at the same soft
 * intensity `PortfolioPanel`'s own coverage notice already uses.
 */
import { memo } from 'react';

const RATING_STYLE = {
  Short: { color: 'var(--fg-3)', background: 'var(--bg-3)' },
  Medium: { color: 'var(--fg-2)', background: 'var(--bg-3)' },
  Long: { color: 'var(--warning)', background: 'var(--warning-soft)' },
  'Extremely long': { color: 'var(--danger)', background: 'var(--danger-soft)' },
};

/** `compact` trades the full word for a small dot — the column header's
 *  own cell is too narrow (as little as 90px, shared with a sort label
 *  and a doc link) for "EXTREMELY LONG" to fit without wrapping the
 *  header onto a second line for every column beside it (TableView.jsx's
 *  own flex-wrap layout breaks every header at once, at the widest
 *  cell). The rating is still the tooltip either way, so nothing here is
 *  only readable at the wide size. */
export const CostBadge = memo(function CostBadge({ cost, className = '', compact = false }) {
  if (!cost?.rating) return null;
  const style = RATING_STYLE[cost.rating] || RATING_STYLE.Medium;
  const title = `Cost to compute: ${cost.rating} (score ${cost.score}) — how this is derived is documented on the measurement's own doc page.`;

  if (compact) {
    return (
      <span
        title={title}
        aria-label={`Cost to compute: ${cost.rating}`}
        className={`flex-none w-[7px] h-[7px] rounded-full ${className}`}
        style={{ background: style.color }}
      />
    );
  }

  return (
    <span
      title={title}
      className={`flex-none font-[var(--font-mono)] text-[9px] uppercase tracking-wider rounded-full px-2 py-0.5 whitespace-nowrap ${className}`}
      style={{ color: style.color, background: style.background }}
    >
      {cost.rating}
    </span>
  );
});
