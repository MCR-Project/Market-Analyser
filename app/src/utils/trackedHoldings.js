/**
 * A fund's tracked holdings: its `holdings` without the Untracked ones a
 * Deep-fill laid over it (issue #172).
 *
 * `GET /api/etf/{id}` lists the whole basket while the fund is deep-filled and
 * names the added rows in `untracked`. Everything that reads the *fund* - the
 * Table, the fund metrics - wants all of it. The Matrix and the Network do not:
 * their defaults are a design decision (docs/adr/0006), the Matrix its top *N* by
 * weight and the Network the tracked holdings, and a Deep-fill is not allowed to
 * move them. Hundreds of nodes would also be a different picture, which is the
 * Full view's job (#173), not this one's.
 *
 * Returns the very same array when there is nothing to remove, so a memo keyed
 * on it does not recompute for a fund that is not deep-filled.
 */
export function trackedHoldings(holdings, untracked) {
  if (!holdings) return [];
  if (!untracked || untracked.length === 0) return holdings;
  const skip = new Set(untracked);
  return holdings.filter((h) => !skip.has(h[0]));
}
