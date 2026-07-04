/**
 * Header — sticky top navigation bar.
 *
 * Shows the MCR-3 brand mark, a live/mock data badge (green = backend
 * connected, yellow = using fallback data), and a light/dark theme toggle.
 */
import { memo } from 'react';

export const Header = memo(function Header({ theme, onToggleTheme, isLive = false }) {
  return (
    <header className="sticky top-0 z-40 h-[60px] flex items-center gap-4 px-6 border-b border-[var(--border)]" style={{ background: 'color-mix(in oklab, var(--bg) 82%, transparent)', backdropFilter: 'blur(12px)' }}>
      <div className="flex items-center gap-[11px] flex-none">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--fg)]">
          <path d="M12 3c-2 2.6-2 5.4 0 8 2-2.6 2-5.4 0-8Z" />
          <path d="M12 11c-2.6-1.4-5.4-1.2-8 .4 2.2 2.2 5 2.6 8 1.1Z" />
          <path d="M12 11c2.6-1.4 5.4-1.2 8 .4-2.2 2.2-5 2.6-8 1.1Z" />
          <path d="M12 12.5V21" /><path d="M8.5 21h7" />
        </svg>
        <span className="font-extrabold tracking-tight text-[var(--accent)] text-[16px]">Market Analyser</span>
      </div>

      <div className="flex-1" />

      <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] flex-none flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: isLive ? 'var(--color-success)' : 'var(--color-warning)' }} />
        {isLive ? 'LIVE' : 'OFFLINE'} · daily returns
      </span>

      <button
        onClick={onToggleTheme}
        aria-label="Toggle theme"
        className="flex-none w-[38px] h-[38px] grid place-items-center bg-[var(--bg-3)] border border-[var(--border)] rounded-[var(--radius-md)] text-[var(--fg-1)] cursor-pointer"
      >
        {theme === 'light' ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></svg>
        )}
      </button>
    </header>
  );
});
