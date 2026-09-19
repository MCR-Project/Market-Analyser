/**
 * describeClusters — what the backend's `clusters` (issue #143) mean for one
 * fund's holdings: each cluster's name, size and weight, and which cluster
 * each holding is in. Shared by the matrix's ordering (utils/matrixOrder.js)
 * and the network view's outlines (issue #144) so the two can never name the
 * same cluster differently.
 *
 * A cluster is named after its heaviest holding by fund weight — "NVDA
 * group" — which is always true of it and needs no data beyond the holdings.
 * `holdings` is `[ticker, weight%]` in the fund's own order; `clusters` is
 * the response's list of groups of two or more tickers.
 *
 * A member the fund does not hold is dropped, and a cluster left with fewer
 * than two known members is not a cluster, so a response that has drifted
 * from the holdings (a refetch landing between the two) cannot produce a
 * one-node "group". Membership is per fund, over every holding — never a
 * view's own top-N — which is what keeps a holding's cluster stable however
 * much of the fund a view shows.
 */

/**
 * @param {Array<[string, number]>} holdings
 * @param {string[][]} clusters
 * @returns {{
 *   list: Array<{ key: string, name: string, size: number, total: number, lead: number, members: string[] }>,
 *   byKey: Map<string, object>,
 *   clusterOf: Record<string, object>,
 * }}
 *   `list` in the order `clusters` came in; `key` is the heaviest holding's
 *   ticker (a cluster's stable id); `total` is the members' summed fund
 *   weight; `lead` is the heaviest holding's position in `holdings`, used to
 *   break ties between equal totals; `clusterOf` maps every clustered
 *   ticker to its entry.
 */
export function describeClusters(holdings, clusters) {
  const rank = new Map(holdings.map((h, i) => [h[0], i]));
  const weightOf = new Map(holdings.map(h => [h[0], h[1]]));

  const list = [];
  const byKey = new Map();
  const clusterOf = {};
  (clusters ?? []).forEach(group => {
    const members = group.filter(t => weightOf.has(t));
    if (members.length < 2) return;
    const heaviest = members.reduce((best, t) => (weightOf.get(t) > weightOf.get(best) ? t : best), members[0]);
    const entry = {
      key: heaviest,
      name: `${heaviest} group`,
      size: members.length,
      total: members.reduce((sum, t) => sum + weightOf.get(t), 0),
      lead: rank.get(heaviest),
      members,
    };
    list.push(entry);
    byKey.set(heaviest, entry);
    members.forEach(t => { clusterOf[t] = entry; });
  });

  return { list, byKey, clusterOf };
}
