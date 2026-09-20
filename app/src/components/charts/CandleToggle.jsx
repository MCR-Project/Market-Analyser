/**
 * CandleToggle — the one switch between a price chart's line and its candles
 * (issue #152). Every price chart shows this same button beside its timeframe
 * tabs, and they all read the one store (`useCandles`), so pressing it on any
 * of them changes all of them, the ones behind an open popup included.
 *
 * A display choice, not a write: it stays on a read-only (shared) portfolio's
 * holding popup, which removes every control that would change the portfolio
 * but not one that only changes how a price is drawn.
 */
import { memo } from 'react';
import { useCandles } from '../../hooks/useCandles';

export const CandleToggle = memo(function CandleToggle() {
  const [on, setOn] = useCandles();

  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={() => setOn(!on)}
      title={on ? 'Show a line instead of candles' : 'Show candles instead of a line'}
      className="inline-flex items-center gap-1.5 px-2.5 py-[6px] rounded-[var(--radius-md)] border cursor-pointer font-[var(--font-mono)] text-xs transition-all duration-150 flex-none"
      style={{
        fontWeight: on ? 700 : 500,
        background: on ? 'var(--accent-soft)' : 'transparent',
        borderColor: on ? 'var(--accent-ring)' : 'var(--border)',
        color: on ? 'var(--accent)' : 'var(--fg-2)',
      }}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
        <path d="M7 3v3M7 14v4M17 6v3M17 17v3" />
        <rect x="4.5" y="6" width="5" height="8" rx="1" fill="currentColor" />
        <rect x="14.5" y="9" width="5" height="8" rx="1" />
      </svg>
      Candles
    </button>
  );
});
