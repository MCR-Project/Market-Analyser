/**
 * Weight arithmetic shared by anything that builds a basket.
 *
 * The simulation normalises weights itself (see
 * backend/services/portfolio.py — 30/30/30 and 33.33/33.33/33.33 are the
 * same portfolio), so this is about what a person is shown rather than
 * what is computed: a freshly copied fund should read as a set of weights
 * that add up, not as 99.99%.
 */

/** Two decimals is what a weight is written to everywhere in the app, and
 *  what `etf_holdings.weight` stores. */
const DP = 2;

function round(value) {
  return Math.round(value * 10 ** DP) / 10 ** DP;
}

/**
 * Rescale `holdings` so their weights total exactly 100.
 *
 * Rounding each share to two decimals leaves a few hundredths
 * unaccounted for, which would show a freshly copied fund adding up to
 * 99.99% — a number nobody can act on and everybody has to wonder about.
 * The residue goes onto the largest holding, where a hundredth of a
 * percent is invisible; spreading it evenly instead would leave several
 * holdings ending in odd digits for no reason anyone could see.
 *
 * Weights that are all zero come back untouched: there is no ratio to
 * preserve, and inventing one would be a decision this does not get to
 * make.
 */
export function normaliseWeights(holdings) {
  const total = holdings.reduce((sum, h) => sum + h.weight, 0);
  if (total <= 0) return holdings.map(h => ({ ...h, weight: 0 }));

  const scaled = holdings.map(h => ({ ...h, weight: round((h.weight / total) * 100) }));
  const residue = round(100 - scaled.reduce((sum, h) => sum + h.weight, 0));
  if (residue !== 0) {
    const largest = scaled.reduce((best, h) => (h.weight > best.weight ? h : best), scaled[0]);
    largest.weight = round(largest.weight + residue);
  }
  return scaled;
}

/** What a set of weights currently adds up to, rounded the way it is
 *  displayed so the total never disagrees with the rows above it. */
export function totalWeight(holdings) {
  return round(holdings.reduce((sum, h) => sum + h.weight, 0));
}
