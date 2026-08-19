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
 * Returns {} for a network-level error, leaving the defaults in place.
 */
export function describeFetchError(error) {
  const status = error?.status;
  if (status === undefined) return {};
  if (status === 404) {
    return {
      title: 'No data for this ETF',
      message: 'The backend has no metadata or holdings for the selected ETF.',
    };
  }
  if (status === 429 || status >= 500) {
    return {
      title: 'Live data temporarily unavailable',
      message: 'The backend is running, but the market-data source behind it did not answer. Retrying automatically.',
    };
  }
  return {
    title: 'Request rejected',
    message: `The backend refused the request (HTTP ${status}).`,
  };
}
