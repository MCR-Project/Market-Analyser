/**
 * FullViewHeader — what a Full view says about itself (issue #173): which fund and
 * which picture, over what window, as of when, how many holdings are drawn and which
 * were left out, and the way back to the normal view.
 *
 * The times are the Deep-fill's own, read off the result and not the clock: the page
 * is a snapshot, and says so. When the server's copy has expired since the page
 * opened, that is said too — the picture on screen is still the one it was drawn
 * as, and nothing here is recomputed or refreshed behind it.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { formatMoment } from '../../utils/deepFill';
import { FULL_VIEW_KINDS, fullViewPath, normalViewPath } from '../../utils/fullViewRoute';

const KIND_WORDS = { matrix: 'Matrix', network: 'Network' };
const PERIOD_WORDS = { '1y': 'Past year' };
/** The longest delay a browser timer can hold; a longer one fires at once. */
const MAX_TIMER_MS = 2147483647;

/** Whether `expiresAt` has passed, flipping while the page is open. */
function useExpired(expiresAt) {
  const [expired, setExpired] = useState(false);
  useEffect(() => {
    const at = Date.parse(expiresAt);
    if (Number.isNaN(at)) return undefined;
    const timer = setTimeout(() => setExpired(true), Math.min(MAX_TIMER_MS, Math.max(0, at - Date.now())));
    return () => clearTimeout(timer);
  }, [expiresAt]);
  return expired;
}

export function FullViewHeader({ fund, kind }) {
  const expired = useExpired(fund.expiresAt);
  const excluded = Object.entries(fund.excluded);
  const asOf = formatMoment(fund.asOf);
  const until = formatMoment(fund.expiresAt);

  return (
    <header className="flex-none flex flex-col gap-2">
      <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
        <Link
          to={normalViewPath(fund.etfId, kind)}
          className="font-[var(--font-mono)] text-xs font-semibold text-[var(--accent)] no-underline hover:underline"
        >
          ← {fund.etfId} {KIND_WORDS[kind]}
        </Link>
        <h1 className="m-0 text-lg font-extrabold tracking-tight text-[var(--fg)]">
          {fund.etfId} <span className="font-semibold text-[var(--fg-2)]">· Full {kind}</span>
        </h1>
        <nav aria-label="Full view" className="flex gap-1 ml-auto">
          {FULL_VIEW_KINDS.map((k) => (
            <Link
              key={k}
              to={{ pathname: fullViewPath(fund.etfId, k) }}
              aria-current={k === kind ? 'page' : undefined}
              className="px-3 py-1.5 font-[var(--font-mono)] text-xs no-underline rounded-[var(--radius-sm)]"
              style={{
                fontWeight: k === kind ? 700 : 500,
                background: k === kind ? 'var(--bg-3)' : 'transparent',
                color: k === kind ? 'var(--fg)' : 'var(--fg-2)',
              }}
            >
              {KIND_WORDS[k]}
            </Link>
          ))}
        </nav>
      </div>

      <p className="m-0 flex flex-wrap gap-x-3 gap-y-1 font-[var(--font-mono)] text-xs text-[var(--fg-2)]">
        <span>{PERIOD_WORDS[fund.period] ?? fund.period}</span>
        <span aria-hidden="true">·</span>
        <span>{fund.n} holdings drawn</span>
        {asOf && (<><span aria-hidden="true">·</span><span>as of {asOf}</span></>)}
        {until && !expired && (<><span aria-hidden="true">·</span><span>kept until {until}</span></>)}
        {expired && (
          <><span aria-hidden="true">·</span>
          <span className="text-[var(--warning)]">
            the server&apos;s copy has expired — this is the picture as it was drawn
          </span></>
        )}
      </p>

      {excluded.length > 0 && (
        <details className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">
          <summary className="cursor-pointer">
            {excluded.length} {excluded.length === 1 ? 'holding is' : 'holdings are'} left out: no usable history to draw
          </summary>
          <ul className="m-0 mt-1.5 pl-5 max-h-40 overflow-auto text-[var(--fg-3)]">
            {excluded.map(([ticker, reason]) => (
              <li key={ticker}><span className="text-[var(--fg-1)]">{ticker}</span> — {reason}</li>
            ))}
          </ul>
        </details>
      )}
    </header>
  );
}
