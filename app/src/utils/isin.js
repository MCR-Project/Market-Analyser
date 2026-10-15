/**
 * isin — is what somebody typed shaped like an ISIN (issue #191).
 *
 * The ticker search asks this of its settled query to decide which endpoint
 * to call: an ISIN-shaped value goes to `GET /api/tickers/isin/{isin}`, and
 * anything else to the as-you-type search, which never calls it.
 *
 * **Shape only, on purpose.** Two letters, nine letters or digits, one final
 * digit, and exactly that long. The check digit is the backend's to judge
 * (issue #190), so the rule exists once: a code of the right shape with a
 * wrong digit is sent anyway and comes back as the backend's own 400, in
 * words, rather than being refused here with a second, drifting opinion.
 *
 * Case and surrounding spaces are forgiven - an ISIN is pasted from a
 * statement, and both are artefacts of pasting - but spaces inside the code
 * are not: nothing the backend would accept has one.
 */
const ISIN_SHAPE = /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/;

export function looksLikeIsin(text) {
  if (typeof text !== 'string') return false;
  return ISIN_SHAPE.test(text.trim().toUpperCase());
}

/**
 * What a failed ISIN lookup says (issue #191). 404 and 400 are stable answers
 * and are worded as such - never "try again" - and neither calls the other's
 * thing wrong: a 404 is a well-formed code Yahoo does not index (some real
 * instruments are not), so it points at the ticker instead of accusing the
 * code. Anything else - 503 while the price source does not answer, a 429, a
 * network failure - is the same "could not be checked just now" the field
 * already says for a symbol, and is retried on the shared schedule.
 */
export function describeIsinError(err, isin) {
  if (err?.status === 404) {
    return 'No listing found for this ISIN — some real instruments are not indexed; try its ticker symbol.';
  }
  if (err?.status === 400) {
    return 'This is not a valid ISIN — check how it was typed.';
  }
  return `${isin} could not be checked just now — the price source did not answer.`;
}
