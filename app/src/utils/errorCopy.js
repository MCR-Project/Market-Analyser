// Turns a failed request into the wording an ErrorState panel shows.
// Lives here rather than in ErrorState.jsx so that file stays
// components-only (react-refresh), and next to the other pure helpers.

/**
 * Maps a useFetch error onto this panel's wording.
 *
 * The distinction is the only actionable part for whoever is reading it:
 * the default "backend unreachable" means "start the API server", but the
 * backend answering 503 means it IS running and the problem is behind it.
 * Sending someone to check a server that's already up is a dead end, and
 * that's exactly what this panel used to do for every failure alike.
 * Returns {} for a network-level error, leaving the defaults in place —
 * unless the caller passes `unreachable`, a `{ title, message }` returned
 * in {}'s place (issue #141). The defaults are worded for the dashboard
 * ("Live market data could not be loaded"), which is wrong on a page whose
 * content is not market data; the docs page is prose the backend writes and
 * serves, so it says that instead. Only the no-status case is overridable:
 * the 404 and 5xx wording is unchanged for every caller.
 *
 * `error.retriesExhausted` (set by useFetch once its auto-retry budget
 * runs out, issue #92) picks between two wordings for the same 429/5xx:
 * while it's still retrying, saying so is accurate; once it has stopped,
 * saying so would be a promise this panel can no longer keep, and the
 * Retry button is the only way back.
 */
export function describeFetchError(error, { unreachable } = {}) {
  const status = error?.status;
  if (status === undefined) return unreachable ?? {};
  if (status === 404) {
    return {
      title: 'No data for this ETF',
      message: 'No fund matches this ticker, so there is nothing to load — check the symbol in the address bar. This will not resolve on its own.',
    };
  }
  if (status === 429 || status >= 500) {
    return {
      title: 'Live data temporarily unavailable',
      message: error?.retriesExhausted
        ? 'The backend is running, but the market-data source behind it still has not answered after several attempts. Click Retry to try again.'
        : 'The backend is running, but the market-data source behind it did not answer. Retrying automatically.',
    };
  }
  return {
    title: 'Request rejected',
    message: `The backend refused the request (HTTP ${status}).`,
  };
}
