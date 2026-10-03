/**
 * The side panel's pair insights - the strongest pair, the loosest pair and the
 * "hub" - for the tickers a view actually draws (issue #172).
 *
 * `GET /api/correlation/{id}` answers these over the whole matrix, which for a
 * deep-filled fund includes the Untracked holdings the Matrix and the Network do
 * not draw, so they would name pairs the reader cannot find on the screen. This
 * recomputes them over a subset, with the backend's own rules
 * (`compute_correlation_matrix`): an unknown (null) pair is skipped, never read
 * as 0; the hub is the ticker with the highest average over the pairs it has; and
 * with nothing to report each is null, not a made-up value.
 */
export function pairInsights(matrix, tickers) {
  let strongest = null;
  let weakest = null;
  let hub = null;

  tickers.forEach((a, i) => {
    const others = tickers
      .filter(b => b !== a)
      .map(b => matrix?.[a]?.[b])
      .filter(v => v != null);
    if (others.length > 0) {
      const avgCorr = others.reduce((sum, v) => sum + v, 0) / others.length;
      if (hub === null || avgCorr > hub.avgCorr) hub = { ticker: a, avgCorr };
    }

    for (let j = i + 1; j < tickers.length; j++) {
      const b = tickers[j];
      const value = matrix?.[a]?.[b];
      if (value == null) continue;
      if (strongest === null || value > strongest.value) strongest = { a, b, value };
      if (weakest === null || value < weakest.value) weakest = { a, b, value };
    }
  });

  return { strongest, weakest, hub };
}
