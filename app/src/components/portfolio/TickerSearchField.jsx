/**
 * TickerSearchField — pick a symbol, and be sure it can be priced.
 *
 * Two endpoints, each doing the job it was built for (#58): searching
 * lists the tracked universe from a cached snapshot and never leaves the
 * process, so typing costs nothing; the symbol that gets picked is
 * resolved, which is what confirms an untracked ticker exists and has
 * price history before anything is done with it.
 *
 * Used for both of the places a ticker is chosen — a holding to add and a
 * benchmark to compare against — because the question is identical and
 * only what happens afterwards differs. The caller gets the resolved
 * symbol, which carries the earliest date it can be priced from.
 */
import { useMemo, useState } from 'react';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { useFetch } from '../../hooks/useFetch';
import { ApiError, api } from '../../utils/api';

/** What could be a ticker rather than the start of a company name — the
 *  shape the resolver accepts, so the "add it anyway" row is only offered
 *  when it could possibly work. */
const SYMBOL_SHAPE = /^[A-Za-z0-9][A-Za-z0-9.-]{0,11}$/;

export function TickerSearchField({
  placeholder,
  ariaLabel,
  exclude,
  disabled,
  onResolved,
  className = '',
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(null);
  const [problem, setProblem] = useState(null);

  const debounced = useDebouncedValue(query.trim(), 200);

  const { data: results } = useFetch(
    (signal) => (open ? api.searchTickers(debounced, { limit: 8, signal }) : Promise.resolve(null)),
    [debounced, open],
    { fallback: null }
  );

  const held = useMemo(() => new Set(exclude || []), [exclude]);

  const trimmed = query.trim();
  const typed = trimmed.toUpperCase();
  // Results describe `debounced`, which lags what has been typed. Until
  // the two agree the list on screen answers a question nobody is asking
  // any more - and acting on it picks the wrong ticker entirely: Enter on
  // a freshly typed symbol would take the first row of the *previous*
  // query, which is how "ZZZZQQ" once added AAPL.
  const settled = debounced === trimmed && results !== null;
  const matches = settled ? results.filter(result => !held.has(result.symbol)) : [];

  const offerUntracked =
    settled &&
    SYMBOL_SHAPE.test(typed) &&
    !held.has(typed) &&
    !matches.some(result => result.symbol === typed);

  const pick = async (symbol) => {
    setProblem(null);
    setPending(symbol);
    try {
      // The resolver is the gate: it answers 404 for a symbol with no
      // price history at all, and reports the first close for one that
      // has some.
      const resolved = await api.resolveTicker(symbol);
      onResolved(resolved);
      setQuery('');
      setOpen(false);
    } catch (err) {
      // The list is absolutely positioned over the space the message
      // occupies, so leaving it open would hide the very explanation of
      // why nothing happened.
      setOpen(false);
      setProblem(
        err instanceof ApiError && err.status === 404
          ? `No price history for ${symbol}, so it cannot be simulated. Check the symbol.`
          : `${symbol} could not be checked just now — the price source did not answer.`
      );
    } finally {
      setPending(null);
    }
  };

  return (
    <div className={className}>
      <div className="relative">
        <input
          value={query}
          disabled={disabled}
          onInput={e => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          // A click on a result blurs the input before it fires, so the
          // list has to outlive the blur by a tick.
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={e => {
            if (e.key === 'Escape') { setOpen(false); e.currentTarget.blur(); }
            if (e.key === 'Enter') {
              // Only ever acts on results that answer what is in the box.
              if (!settled) return;
              const first = matches[0];
              if (first) pick(first.symbol);
              else if (offerUntracked) pick(typed);
            }
          }}
          placeholder={placeholder}
          aria-label={ariaLabel}
          className="w-full h-[38px] px-3 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-md)] text-[13px] text-[var(--fg)] outline-none focus:border-[var(--accent-ring)] disabled:opacity-50"
        />

        {open && !settled && trimmed !== '' && (
          <div className="absolute z-30 left-0 right-0 top-[42px] px-3 py-2 bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] text-[12px] text-[var(--fg-2)]">
            Searching…
          </div>
        )}

        {open && settled && (matches.length > 0 || offerUntracked) && (
          <ul className="corr-scroll absolute z-30 left-0 right-0 top-[42px] max-h-[240px] overflow-y-auto list-none m-0 p-1.5 bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-md)] shadow-[var(--shadow-lg)]">
            {matches.map(result => (
              <li key={result.symbol}>
                <button
                  onMouseDown={e => e.preventDefault()}
                  onClick={() => pick(result.symbol)}
                  disabled={!!pending}
                  className="w-full flex items-baseline gap-2.5 px-2.5 py-2 text-left rounded-[var(--radius-sm)] border-none bg-transparent cursor-pointer hover:bg-[var(--bg-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                >
                  <span className="font-[var(--font-mono)] text-[12.5px] font-bold text-[var(--fg)] flex-none">
                    {result.symbol}
                  </span>
                  <span className="text-[12px] text-[var(--fg-2)] truncate">{result.name}</span>
                  {result.kind === 'etf' && <span className="eyebrow flex-none ml-auto">FUND</span>}
                </button>
              </li>
            ))}
            {offerUntracked && (
              <li>
                <button
                  onMouseDown={e => e.preventDefault()}
                  onClick={() => pick(typed)}
                  disabled={!!pending}
                  className="w-full flex items-baseline gap-2.5 px-2.5 py-2 text-left rounded-[var(--radius-sm)] border-none bg-transparent cursor-pointer hover:bg-[var(--bg-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                >
                  <span className="font-[var(--font-mono)] text-[12.5px] font-bold text-[var(--fg)] flex-none">
                    {typed}
                  </span>
                  <span className="text-[12px] text-[var(--fg-2)]">
                    {pending === typed ? 'checking…' : 'not tracked here — check and add'}
                  </span>
                </button>
              </li>
            )}
          </ul>
        )}
      </div>

      {problem && (
        <p role="alert" className="text-[12.5px] text-[var(--danger)] leading-relaxed m-0 mt-2">
          {problem}
        </p>
      )}
    </div>
  );
}
