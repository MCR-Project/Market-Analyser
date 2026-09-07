/**
 * useComparison — which other portfolios, and which benchmarks, are drawn
 * alongside the one being looked at.
 *
 * Both live in the URL next to the window (#62), so a comparison is a
 * link: `?compare=<id>&benchmark=SPY` reopens the same two portfolios
 * against the same fund over the same dates.
 *
 * A benchmark is deliberately not a portfolio. Answering "did this beat
 * SPY" should not require creating and then deleting a portfolio called
 * SPY, so a benchmark is a ticker that lives in the URL, is simulated as
 * a basket of one, and never touches the library.
 *
 * Portfolio ids are only meaningful in the browser that made them, so a
 * shared link comparing two portfolios shows the sender's second one as
 * unknown rather than as somebody else's data. The page drops ids it
 * cannot find.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { readList, withParams } from '../utils/searchParams';

/** Enough lines to tell apart on one chart, and enough requests to keep a
 *  comparison quick: each line is its own simulation. */
export const MAX_LINES = 6;

export function useComparison(primaryId) {
  const [params, setParams] = useSearchParams();

  // The primary is always on the chart and never in the list - it is the
  // portfolio the page is about, not something added to it.
  const compareIds = useMemo(
    () => readList(params, 'compare').filter(id => id !== primaryId),
    [params, primaryId]
  );
  const benchmarks = useMemo(
    () => readList(params, 'benchmark').map(symbol => symbol.toUpperCase()),
    [params]
  );

  const lineCount = 1 + compareIds.length + benchmarks.length;
  const full = lineCount >= MAX_LINES;

  const write = useCallback((changes) => {
    setParams(current => withParams(current, changes), { replace: true });
  }, [setParams]);

  const toggleCompare = useCallback((id) => {
    const next = compareIds.includes(id)
      ? compareIds.filter(other => other !== id)
      : [...compareIds, id];
    write({ compare: next.join(',') });
  }, [compareIds, write]);

  const addBenchmark = useCallback((symbol) => {
    const upper = symbol.toUpperCase();
    if (benchmarks.includes(upper)) return;
    write({ benchmark: [...benchmarks, upper].join(',') });
  }, [benchmarks, write]);

  const removeBenchmark = useCallback((symbol) => {
    write({ benchmark: benchmarks.filter(other => other !== symbol).join(',') });
  }, [benchmarks, write]);

  const clear = useCallback(() => {
    write({ compare: null, benchmark: null });
  }, [write]);

  return {
    compareIds,
    benchmarks,
    /** More than the primary on the chart: the point at which the stacked
     *  by-stock view stops being what to draw. */
    comparing: compareIds.length + benchmarks.length > 0,
    full,
    toggleCompare,
    addBenchmark,
    removeBenchmark,
    clear,
  };
}
