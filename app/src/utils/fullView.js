/**
 * fullView — turning `GET /api/deep-fill/{id}/full-view` (issue #173) into what
 * the two canvases draw from. Pure: a payload in, a decoded fund out.
 *
 * The backend sends the correlation matrix as a rounded lower triangle
 * (`services/full_view.py`: row `i` is the ρ between `tickers[i]` and each ticker
 * before it) to keep ~500 holdings under a megabyte. This puts the square back, as
 * one `Float32Array` of N × N — 1 MB for 500 holdings, which a nested object of
 * 250,000 entries is not — with `NaN` where there is no correlation. `at(i, j)`
 * is the readable way in, returning `null` for that case: **a pair with too little
 * history is not a zero** (invariant 7), and nothing here lets it become one.
 *
 * The decoded fund is a snapshot: it is never merged with the normal view's data,
 * and nothing is recomputed from it beyond arrangement. What it says (`asOf`,
 * `expiresAt`) is the Deep-fill's own.
 *
 * A payload whose parts disagree (weights not as long as tickers, a triangle row of
 * the wrong length) throws instead of decoding: a matrix read at the wrong stride
 * draws plausible-looking correlations between the wrong pairs, which is worse than
 * drawing nothing.
 */

/**
 * @param {object} payload   the response body
 * @returns {{
 *   etfId: string, asOf: string, expiresAt: string, period: string,
 *   n: number, tickers: string[], weights: number[],
 *   holdings: Array<[string, number]>, indexOf: Map<string, number>,
 *   averages: Record<string, number|null>, clusters: string[][],
 *   excluded: Record<string, string>,
 *   corr: Float32Array, at: (i: number, j: number) => number | null,
 * }}
 */
export function decodeFullView(payload) {
  const bad = (why) => new Error(`Malformed full-view payload: ${why}`);
  if (!payload || !Array.isArray(payload.tickers) || !Array.isArray(payload.weights)) throw bad('no holdings');

  const { tickers, weights } = payload;
  const n = tickers.length;
  if (weights.length !== n) throw bad('weights and tickers differ in length');
  const triangle = payload.correlation?.triangle;
  if (!Array.isArray(triangle) || triangle.length !== n) throw bad('triangle has the wrong number of rows');

  const corr = new Float32Array(n * n);
  for (let i = 0; i < n; i++) {
    const row = triangle[i];
    if (!Array.isArray(row) || row.length !== i) throw bad(`triangle row ${i} has the wrong length`);
    corr[i * n + i] = 1;
    for (let j = 0; j < i; j++) {
      const value = row[j] == null ? NaN : row[j];
      corr[i * n + j] = value;
      corr[j * n + i] = value;
    }
  }

  const averageList = payload.averages ?? [];
  return {
    etfId: payload.etfId,
    asOf: payload.asOf,
    expiresAt: payload.expiresAt,
    period: payload.period,
    n,
    tickers,
    weights,
    holdings: tickers.map((t, i) => [t, weights[i]]),
    indexOf: new Map(tickers.map((t, i) => [t, i])),
    averages: Object.fromEntries(tickers.map((t, i) => [t, averageList[i] ?? null])),
    clusters: payload.clusters ?? [],
    excluded: payload.excluded ?? {},
    corr,
    at: (i, j) => {
      const value = corr[i * n + j];
      return Number.isNaN(value) ? null : value;
    },
  };
}

/** A fund weight (percent) with enough places that a holding of a few hundredths of
 *  a percent — most of a 500-holding fund — does not read as nothing. */
export function fmtWeight(weight) {
  if (weight >= 1) return `${weight.toFixed(1)}%`;
  return `${weight >= 0.1 ? weight.toFixed(2) : weight.toFixed(3)}%`;
}
