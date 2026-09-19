/**
 * matrixOrder — the order and grouping the correlation matrix tab draws in
 * (issue #143). Pure: holdings, the backend's clusters and the two toggle
 * values in; the tickers in drawing order and the labelled sections out.
 * It lives here rather than in `MatrixView` so the rules below are one
 * readable function instead of being tangled into the JSX — there is no
 * frontend test runner, so this is also the part worth reading carefully.
 *
 * **Membership comes from the whole fund, the display from the top N.**
 * `clusters` (from `/api/correlation`) was computed over every holding, so
 * a ticker's cluster is the same whatever the "stocks" slider says; the
 * matrix then shows only the first `n` holdings by weight, in cluster
 * order. Clustering just the displayed N instead would have a stock change
 * cluster as the slider is dragged.
 *
 * Three orders (`?matrixOrder=`):
 *   - `cluster` (default): clusters in turn, heaviest total fund weight
 *     first, each a labelled section; then an "Others" band; then a
 *     "No history" band.
 *   - `alpha`: A–Z, no sections.
 *   - `weight`: the fund's own order, heaviest holding first, no sections.
 * and, inside each cluster (and "Others"), `?matrixWithin=` — `weight`
 * (default) or `alpha`.
 *
 * What the two bands are, kept apart on purpose so one word never means
 * two things:
 *   - **Others** — a ticker that has history but no block to sit in *on
 *     screen*: it joined no cluster, or its cluster has only this one
 *     member among the N shown. This is a display rule only; the real
 *     cluster is still in `clusterOf` (and named in the ticker's tooltip),
 *     so the matrix does not turn into a diagonal of one-cell blocks at a
 *     small N.
 *   - **No history** — `averages[t]` is null (or absent): no pair with any
 *     peer could be computed at all (issue #97). Not "uncorrelated" — there
 *     is nothing to say about it.
 *
 * When no cluster has two or more visible names *and* every ticker has
 * history, there is nothing to set apart, so `sections` is null and the
 * matrix draws as a plain list in the `within` order rather than under one
 * band labelled "Others" that would imply clusters exist. If some ticker
 * has no history the bands still appear — everything else under "Others"
 * (accurate: none of it is in a block) — because "No history" must never
 * be left unlabelled.
 */

import { describeClusters } from './clusters';

export const MATRIX_ORDERS = ['cluster', 'alpha', 'weight'];
export const MATRIX_WITHIN = ['weight', 'alpha'];
export const DEFAULT_ORDER = 'cluster';
export const DEFAULT_WITHIN = 'weight';

const byAlpha = (a, b) => a.localeCompare(b);

/**
 * @param {object} args
 * @param {Array<[string, number]>} args.holdings  the fund's holdings, [ticker, weight%], heaviest first
 * @param {string[][]} args.clusters               the backend's groups of two or more tickers
 * @param {Record<string, number|null>} args.averages  each ticker's average ρ to its peers, null when it has none
 * @param {number} args.n                          how many holdings the matrix shows
 * @param {string} args.order                      one of MATRIX_ORDERS
 * @param {string} args.within                     one of MATRIX_WITHIN
 * @returns {{
 *   tickers: string[],
 *   sections: null | Array<{ key: string, kind: 'cluster'|'others'|'nohistory', label: string, start: number, count: number, size: number }>,
 *   clusterOf: Record<string, { name: string, size: number }>,
 * }}
 *   (each `clusterOf` entry is `describeClusters`' entry for that cluster
 *   — see utils/clusters.js, which also names it after its heaviest
 *   holding — and so carries the fields the ordering itself uses: `key`,
 *   `total`, `lead`, `members`. Callers should read only `name` and `size`.)
 *   `tickers` is the drawing order for rows and columns alike. `sections`
 *   partitions it (`start` indexes into `tickers`); `size` is the cluster's
 *   full-fund size, so a section can say "4 of 6" when part of it is off
 *   screen. `clusterOf` covers every clustered holding in the fund,
 *   visible or not.
 */
export function orderMatrix({ holdings, clusters, averages, n, order, within }) {
  const rank = new Map(holdings.map((h, i) => [h[0], i]));
  const byWeight = (a, b) => rank.get(a) - rank.get(b);
  const inGroup = within === 'alpha' ? byAlpha : byWeight;

  // Every cluster in the whole fund, named after its heaviest holding.
  const { byKey: info, clusterOf } = describeClusters(holdings, clusters);

  const shown = holdings.slice(0, n).map(h => h[0]);

  if (order === 'alpha') return { tickers: [...shown].sort(byAlpha), sections: null, clusterOf };
  if (order === 'weight') return { tickers: shown, sections: null, clusterOf };

  const noHistory = shown.filter(t => averages?.[t] == null);
  const withHistory = shown.filter(t => averages?.[t] != null);

  const visible = new Map();
  withHistory.forEach(t => {
    const c = clusterOf[t];
    if (!c) return;
    if (!visible.has(c.key)) visible.set(c.key, []);
    visible.get(c.key).push(t);
  });

  // Heaviest cluster (by the whole cluster's fund weight, not just its
  // visible part — so the order does not shuffle as the slider moves) first.
  const blocks = [...visible.entries()]
    .filter(([, members]) => members.length >= 2)
    .map(([key, members]) => ({ entry: info.get(key), members: members.sort(inGroup) }))
    .sort((a, b) => b.entry.total - a.entry.total || a.entry.lead - b.entry.lead);

  const inBlock = new Set(blocks.flatMap(b => b.members));
  const others = withHistory.filter(t => !inBlock.has(t)).sort(inGroup);

  if (blocks.length === 0 && noHistory.length === 0) {
    return { tickers: [...shown].sort(inGroup), sections: null, clusterOf };
  }

  const sections = [];
  const tickers = [];
  const add = (key, kind, label, size, members) => {
    sections.push({ key, kind, label, start: tickers.length, count: members.length, size });
    tickers.push(...members);
  };
  blocks.forEach(b => add(b.entry.key, 'cluster', b.entry.name, b.entry.size, b.members));
  if (others.length) add('__others', 'others', 'Others', others.length, others);
  if (noHistory.length) add('__nohistory', 'nohistory', 'No history', noHistory.length, noHistory.sort(inGroup));

  return { tickers, sections, clusterOf };
}
