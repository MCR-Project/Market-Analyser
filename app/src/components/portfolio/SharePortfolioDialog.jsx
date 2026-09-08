/**
 * SharePortfolioDialog — the link, and what it does and does not carry.
 *
 * The link is shown rather than only copied. Copying can fail for reasons
 * that have nothing to do with this app — clipboard permission, an
 * insecure origin — and a button that reports success it did not have is
 * worse than no button. The field is the fallback: it holds the same
 * text, selected, ready to be copied by hand.
 *
 * The two sentences under it are the point of the dialog. A link that
 * contains a portfolio is a surprising thing, and both of the surprises
 * are worth saying before somebody sends it: the portfolio travels
 * *inside* the link rather than being stored anywhere, and it is a
 * snapshot rather than a subscription.
 *
 * Keyboard behaviour (Escape, focus trap, focus returned to whatever
 * opened it) comes from Overlay, to the standard set in #24.
 */
import { useState } from 'react';
import { Overlay } from '../ui/Overlay';

export function SharePortfolioDialog({ portfolio, url, windowLabel, onClose }) {
  // null: not tried. true: in the clipboard. false: it refused, and the
  // field is now the way to do it.
  const [copied, setCopied] = useState(null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false);
      document.getElementById('share-link')?.select();
    }
  };

  return (
    <Overlay
      onClose={onClose}
      ariaLabel={`Share ${portfolio.name}`}
      className="fixed inset-0 z-80 flex items-start justify-center pt-[16vh] px-5 pb-5"
      style={{ background: 'color-mix(in oklab, var(--bg-inset) 70%, transparent)', backdropFilter: 'blur(3px)' }}
      contentClassName="w-full max-w-[560px] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] p-5 animate-[corrPop_var(--dur-fast)_var(--ease-out)]"
    >
      <div className="eyebrow mb-2">SHARE PORTFOLIO</div>
      <p className="text-[14px] text-[var(--fg)] m-0 mb-3 leading-relaxed">
        This link contains “<strong className="font-bold">{portfolio.name}</strong>” —
        its {portfolio.holdings?.length || 0} holdings, their weights, the
        amount and the method{windowLabel ? `, over ${windowLabel}` : ''}.
      </p>

      <div className="flex items-center gap-2 mb-3">
        <input
          id="share-link"
          readOnly
          value={url}
          aria-label="Share link"
          onFocus={e => e.target.select()}
          className="flex-1 min-w-0 h-[34px] px-2.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-md)] font-[var(--font-mono)] text-[12px] text-[var(--fg-1)] outline-none focus:border-[var(--accent-ring)]"
        />
        <button
          onClick={copy}
          className="flex-none px-3.5 h-[34px] text-[13px] font-semibold text-[var(--accent)] bg-[var(--accent-soft)] border border-[var(--accent-ring)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--accent-ring)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>

      {copied === false && (
        <p role="status" className="text-[12.5px] text-[var(--warning)] leading-relaxed m-0 mb-3">
          The browser would not let the page use the clipboard. The link is
          selected above — copy it from there.
        </p>
      )}

      <p className="text-[12.5px] text-[var(--fg-2)] leading-relaxed m-0">
        The portfolio travels inside the link itself: nothing is uploaded,
        and there is no copy on a server. Whoever opens it sees a{' '}
        <strong className="font-bold text-[var(--fg-1)]">snapshot</strong> —
        it will not follow the changes you make here afterwards, and they
        can save their own copy to work on.
      </p>

      <div className="flex justify-end mt-4">
        <button
          onClick={onClose}
          className="px-3.5 py-2 text-[13px] font-semibold text-[var(--fg-1)] bg-[var(--bg-2)] border border-[var(--border)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-3)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          Done
        </button>
      </div>
    </Overlay>
  );
}
