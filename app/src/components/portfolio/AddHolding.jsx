/**
 * AddHolding — putting a ticker into a portfolio.
 *
 * Two different questions, answered by the two endpoints built for them
 * (#58): searching lists the tracked universe from a cached snapshot and
 * never leaves the process, so typing costs nothing; picking one symbol
 * resolves it, which is what confirms an untracked ticker exists and can
 * be priced before it is allowed in.
 *
 * That second step is not ceremony. A portfolio may hold anything
 * yfinance can price, so a typo looks exactly like a small foreign
 * listing until something asks — and an unpriceable holding would sit in
 * the portfolio as a silent pile of cash. Resolving also reports the
 * earliest close available, which is how the row can say up front that a
 * holding lists partway through the window rather than leaving someone to
 * wonder why their backtest starts flat.
 */
import { useMemo, useRef, useState } from 'react';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { useFetch } from '../../hooks/useFetch';
import { api } from '../../utils/api';
import { ApiError } from '../../utils/api';

/** What could be a ticker rather than the start of a company name — the
 *  shape the resolver accepts, so the "add it anyway" row is only offered
 *  when it could possibly work. */
const SYMBOL_SHAPE = /^[A-Za-z0-9][A-Za-z0-9.-]{0,11}$/;

export function AddHolding({ existing, windowStart, onAdd }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(null);
  const [problem, setProblem] = useState(null);
  const [note, setNote] = useState(null);
  const inputRef = useRef(null);

  const debounced = useDebouncedValue(query.trim(), 200);

  const { data: results } = useFetch(
    (signal) => (open ? api.searchTickers(debounced, { limit: 8, signal }) : Promise.resolve(null)),
    [debounced, open],
    { fallback: null }
  );

  const held = useMemo(() => new Set(existing.map(h => h.ticker)), [existing]);

  const trimmed = query.trim();
  const typed = trimmed.toUpperCase();
  // Results describe `debounced`, which lags what has been typed. Until
  // the two agree the list on screen answers a question nobody is asking
  // any more - and acting on it adds the wrong ticker entirely: Enter on
  // a freshly typed symbol would take the first row of the *previous*
  // query, which is how "ZZZZQQ" once added AAPL.
  const settled = debounced === trimmed && results !== null;
  const matches = settled ? results.filter(r => !held.has(r.symbol)) : [];

  // Offered when nothing tracked matches exactly: the universe is only
  // what this app follows, not what can be held.
  const offerUntracked =
    settled &&
    SYMBOL_SHAPE.test(typed) &&
    !held.has(typed) &&
    !matches.some(r => r.symbol === typed);

  const add = async (symbol) => {
    setProblem(null);
    setNote(null);
    setPending(symbol);
    try {
      // The resolver is the gate: it answers 404 for a symbol with no
      // price history at all, and reports the first close for one that
      // has some.
      const resolved = await api.resolveTicker(symbol);
      onAdd(resolved.symbol);
      setQuery('');
      setOpen(false);
      if (windowStart && resolved.firstDate && resolved.firstDate > windowStart) {
        setNote(
          `${resolved.symbol} has prices from ${resolved.firstDate}. Until then its share of the portfolio waits in cash.`
        );
      }
    } catch (err) {
      // The list is absolutely positioned over the space the message
      // occupies, so leaving it open would hide the very explanation of
      // why nothing was added.
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
    <div className="mb-3">
      <div className="relative">
        <input
          ref={inputRef}
          value={query}
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
              if (first) add(first.symbol);
              else if (offerUntracked) add(typed);
            }
          }}
          placeholder="Add a holding — ticker or name"
          aria-label="Add a holding"
          className="w-full h-[38px] px-3 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-md)] text-[13px] text-[var(--fg)] outline-none focus:border-[var(--accent-ring)]"
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
                  onClick={() => add(result.symbol)}
                  disabled={!!pending}
                  className="w-full flex items-baseline gap-2.5 px-2.5 py-2 text-left rounded-[var(--radius-sm)] border-none bg-transparent cursor-pointer hover:bg-[var(--bg-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                >
                  <span className="font-[var(--font-mono)] text-[12.5px] font-bold text-[var(--fg)] flex-none">
                    {result.symbol}
                  </span>
                  <span className="text-[12px] text-[var(--fg-2)] truncate">{result.name}</span>
                  {result.kind === 'etf' && (
                    <span className="eyebrow flex-none ml-auto">FUND</span>
                  )}
                </button>
              </li>
            ))}
            {offerUntracked && (
              <li>
                <button
                  onMouseDown={e => e.preventDefault()}
                  onClick={() => add(typed)}
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
      {note && (
        <p role="status" className="text-[12.5px] text-[var(--fg-2)] leading-relaxed m-0 mt-2">
          {note}
        </p>
      )}
    </div>
  );
}
