/**
 * useStockComparison — the second stock, if any, shown alongside the
 * primary one on the Stock page (issue #160).
 *
 * `?compare=` holds at most one ticker, never a list — structurally, not
 * just by convention. `readList`-style parsing was deliberately not used
 * here: even a hand-edited URL like `?compare=TSLA,AMD` reads as no
 * comparison at all (the raw value doesn't match one symbol's shape)
 * rather than as two tickers, which is what actually keeps the page's own
 * cap (the primary stock, plus one) from ever being bypassed through the
 * URL — there is no code path here that could produce a third line even
 * if asked to, the same "enforced by the data model, not hidden in the
 * UI" reasoning `docs/adr/0004` already applies to an unclassified symbol.
 *
 * The same param name `/portfolio/...` uses for its own `?compare=` list —
 * reused for the same reason `?window=` already is across routes: the
 * concept ("what else is being shown alongside this") is the same, and
 * the two can never collide since they live on different routes with
 * completely different id spaces (a saved portfolio's id there, a raw
 * ticker symbol here).
 */
import { useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { withParams } from '../utils/searchParams';

// What a ticker can look like — the same shape TickerSearchField already
// gates its own "add it anyway" row on.
const SYMBOL_SHAPE = /^[A-Za-z0-9][A-Za-z0-9.-]{0,11}$/;

export function useStockComparison(primaryTicker) {
  const [params, setParams] = useSearchParams();

  const raw = (params.get('compare') || '').trim().toUpperCase();
  // Canonicalise rather than error: anything that isn't one real symbol's
  // shape, or that names the stock already open, reads as no comparison
  // at all rather than a complaint about the URL.
  const compareTicker = raw && SYMBOL_SHAPE.test(raw) && raw !== primaryTicker ? raw : null;

  const setCompare = useCallback((symbol) => {
    setParams(current => withParams(current, { compare: symbol ? symbol.toUpperCase() : null }), { replace: true });
  }, [setParams]);

  const clearCompare = useCallback(() => setCompare(null), [setCompare]);

  return { compareTicker, setCompare, clearCompare };
}
