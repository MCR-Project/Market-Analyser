/**
 * TickerSearchField — pick a symbol, and be sure it can be priced.
 *
 * Two endpoints, each doing the job it was built for (#58): searching
 * lists the tracked universe from a cached snapshot and never leaves the
 * process, so typing costs nothing; the symbol that gets picked is
 * resolved, which is what confirms an untracked ticker exists and has
 * price history before anything is done with it.
 *
 * A third path, for an ISIN (issue #191): when the settled query is shaped
 * like one (utils/isin.js), `api.resolveIsin` is asked *instead of* the
 * search - and only then; a typed ticker or a name never calls it - and the
 * box lists the listings that code leads to, each with its exchange and
 * currency. An ISIN is only a way to *find* a ticker: a pick still goes
 * through `api.resolveTicker`, the caller gets a symbol like any other, and
 * nothing about the code is kept. Since an ISIN also fits the symbol shape,
 * the "add it anyway" row is never offered for one - it would send the code
 * to the resolver as if it were a ticker.
 *
 * Currency is why `warnNonUsd` exists. Everything the simulator holds is
 * valued in dollars and a foreign listing is added in its own currency
 * without conversion (README, "Currency"), which an ISIN makes an easy
 * accident: `IWDA.L` is quoted in USD, `TTE.PA` in EUR. Where a pick enters a
 * dollar total (Add holding, the Benchmark bar) the caller turns it on and a
 * listing whose currency is not USD, or could not be read, says "not
 * converted to dollars" on its row. The Stock page shows the currency alone:
 * it is only looking at one instrument. There is still no conversion.
 *
 * A listing already in `exclude` stays on the list, greyed and unclickable,
 * saying why, instead of vanishing - a pasted ISIN that "finds nothing" would
 * read as a failure of the lookup rather than as "you already hold it".
 *
 * Used for the places a ticker is chosen — the Stock page, a holding to add
 * and a benchmark to compare against — because the question is identical and
 * only what happens afterwards differs. The caller gets the resolved
 * symbol, which carries the earliest date it can be priced from.
 */
import { useMemo, useState } from 'react';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { useFetch } from '../../hooks/useFetch';
import { ApiError, api } from '../../utils/api';
import { describeIsinError, looksLikeIsin } from '../../utils/isin';

/** What could be a ticker rather than the start of a company name — the
 *  shape the resolver accepts, so the "add it anyway" row is only offered
 *  when it could possibly work. */
const SYMBOL_SHAPE = /^[A-Za-z0-9][A-Za-z0-9.-]{0,11}$/;

const ROW_CLASS =
  'w-full flex items-baseline gap-2.5 px-2.5 py-2 text-left rounded-[var(--radius-sm)] border-none bg-transparent cursor-pointer hover:bg-[var(--bg-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]';

export function TickerSearchField({
  placeholder,
  ariaLabel,
  exclude,
  disabled,
  onResolved,
  warnNonUsd = false,
  // What a greyed row says after its symbol. The default is the portfolio's
  // (Add holding); the other two callers exclude something else.
  excludedNote = 'is already in this portfolio',
  className = '',
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(null);
  const [problem, setProblem] = useState(null);

  const debounced = useDebouncedValue(query.trim(), 200);

  // Decided on the *settled* value, like everything else here: only an
  // ISIN-shaped value ever reaches the ISIN endpoint, and it never reaches
  // the search.
  const isinCode = looksLikeIsin(debounced) ? debounced.trim().toUpperCase() : null;

  const { data: results, error: lookupError } = useFetch(
    (signal) => {
      if (!open) return Promise.resolve(null);
      return isinCode
        ? api.resolveIsin(isinCode, { signal })
        : api.searchTickers(debounced, { limit: 8, signal });
    },
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
  const caughtUp = debounced === trimmed;
  const settled = caughtUp && results !== null;
  // An ISIN's rows are every listing it leads to, the held ones included
  // (greyed); a search's are only what can still be picked.
  const rows = !settled
    ? []
    : isinCode
      ? results.listings ?? []
      : results.filter(result => !held.has(result.symbol));
  // What Enter may take: never a greyed row.
  const matches = rows.filter(row => !held.has(row.symbol));

  // What a failed lookup says. An empty answer is worded as the 404 it
  // stands in for - the backend answers 404, but an empty list must not read
  // as "nothing wrong, nothing found".
  let isinProblem = null;
  if (isinCode && caughtUp && open) {
    if (lookupError) isinProblem = describeIsinError(lookupError, isinCode);
    else if (settled && rows.length === 0) isinProblem = describeIsinError({ status: 404 }, isinCode);
  }

  const offerUntracked =
    settled &&
    !isinCode &&
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

        {open && !settled && trimmed !== '' && !isinProblem && (
          <div className="absolute z-30 left-0 right-0 top-[42px] px-3 py-2 bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] text-[12px] text-[var(--fg-2)]">
            Searching…
          </div>
        )}

        {open && settled && (rows.length > 0 || offerUntracked) && (
          <ul className="corr-scroll absolute z-30 left-0 right-0 top-[42px] max-h-[240px] overflow-y-auto list-none m-0 p-1.5 bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-md)] shadow-[var(--shadow-lg)]">
            {isinCode
              ? rows.map(listing => (
                  <ListingRow
                    key={listing.symbol}
                    listing={listing}
                    held={held.has(listing.symbol)}
                    heldNote={excludedNote}
                    warnNonUsd={warnNonUsd}
                    busy={!!pending}
                    onPick={() => pick(listing.symbol)}
                  />
                ))
              : rows.map(result => (
                  <li key={result.symbol}>
                    <button
                      onMouseDown={e => e.preventDefault()}
                      onClick={() => pick(result.symbol)}
                      disabled={!!pending}
                      className={ROW_CLASS}
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
                  className={ROW_CLASS}
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

      {(problem || isinProblem) && (
        <p role="alert" className="text-[12.5px] text-[var(--danger)] leading-relaxed m-0 mt-2">
          {problem || isinProblem}
        </p>
      )}
    </div>
  );
}

/**
 * One listing an ISIN leads to: its symbol and name, then where it trades and
 * in what currency. A held one is greyed and not a button at all, so there is
 * nothing to click and nothing for the keyboard to land on.
 */
function ListingRow({ listing, held, heldNote, warnNonUsd, busy, onPick }) {
  const symbol = (
    <span className="font-[var(--font-mono)] text-[12.5px] font-bold text-[var(--fg)] flex-none">
      {listing.symbol}
    </span>
  );

  if (held) {
    return (
      <li>
        <div aria-disabled="true" className="flex items-baseline gap-2.5 px-2.5 py-2 opacity-50 cursor-not-allowed">
          {symbol}
          <span className="text-[12px] text-[var(--fg-2)]">{heldNote}</span>
        </div>
      </li>
    );
  }

  // Never a guessed USD: a listing whose currency could not be read says so,
  // and counts as not-USD for the warning.
  const currency = listing.currency || 'currency unknown';
  const notUsd = listing.currency !== 'USD';
  const where = [listing.exchange, currency].filter(Boolean).join(' · ');

  return (
    <li>
      <button
        onMouseDown={e => e.preventDefault()}
        onClick={onPick}
        disabled={busy}
        className={`${ROW_CLASS} flex-col !items-stretch gap-0.5`}
      >
        <span className="flex items-baseline gap-2.5 min-w-0">
          {symbol}
          <span className="text-[12px] text-[var(--fg-2)] truncate">{listing.name}</span>
        </span>
        <span className="text-[11.5px] text-[var(--fg-3)]">
          {where}
          {!listing.tracked && ' · not tracked here'}
          {warnNonUsd && notUsd && (
            <span className="text-[var(--warning)]"> · not converted to dollars</span>
          )}
        </span>
      </button>
    </li>
  );
}
