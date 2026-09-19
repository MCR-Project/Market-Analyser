/**
 * Editing one query parameter without disturbing the others.
 *
 * react-router's setSearchParams replaces the whole query, so writing
 * `{ window: '5y' }` silently drops anything else living there. Once the
 * URL carries more than one thing — a window *and* a comparison — that
 * turns "change the period" into "change the period and forget what you
 * were comparing it with".
 */

/**
 * The current params with `changes` applied. A null, undefined or empty
 * value removes its key rather than writing an empty one, so a cleared
 * selection leaves the URL clean instead of trailing `&compare=`.
 */
export function withParams(params, changes) {
  const next = new URLSearchParams(params);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === undefined || value === '') next.delete(key);
    else next.set(key, value);
  }
  return next;
}

/** A comma-separated list parameter, as a clean array. */
export function readList(params, key) {
  const raw = params.get(key);
  if (!raw) return [];
  return [...new Set(raw.split(',').map(item => item.trim()).filter(Boolean))];
}

/**
 * A single-choice parameter: the value if it is one of `allowed`, else
 * `fallback`. An unrecognised value is canonicalised to the default rather
 * than treated as an error — a hand-edited or stale link should still open
 * the page, not complain about itself.
 */
export function readChoice(params, key, allowed, fallback) {
  const raw = params.get(key);
  return allowed.includes(raw) ? raw : fallback;
}
