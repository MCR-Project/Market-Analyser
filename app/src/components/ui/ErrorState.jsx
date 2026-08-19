/**
 * ErrorState — visible failure panel shown where live data should be.
 *
 * Rendered when a backend request fails instead of silently showing
 * stale or fabricated data. Offers a Retry button wired to the failed
 * fetch's `retry()` (from useFetch).
 * Props: title, message, onRetry (optional — hides the button when absent).
 *
 * Callers should spread describeFetchError(error) (utils/errorCopy.js) in
 * rather than relying on the defaults — see the note on that function.
 */
import { memo } from 'react';

export const ErrorState = memo(function ErrorState({
  title = 'Backend unreachable',
  message = 'Live market data could not be loaded. Check that the API server is running, then try again.',
  onRetry,
  className = '',
}) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 py-16 px-6 text-center bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] ${className}`}>
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--color-warning)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
        <path d="M12 9v4" /><path d="M12 17h.01" />
      </svg>
      <div className="text-base font-bold text-[var(--fg)]">{title}</div>
      <p className="text-sm text-[var(--fg-2)] leading-relaxed m-0 max-w-[420px]">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-1 px-4 py-2 text-sm font-semibold text-[var(--accent)] bg-[var(--accent-soft)] border border-[var(--accent-ring)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--accent-ring)]"
        >
          Retry
        </button>
      )}
    </div>
  );
});
