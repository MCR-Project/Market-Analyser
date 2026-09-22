// Overridable at build time via VITE_API_BASE (see .env.example) so a built
// bundle can target a non-localhost backend with no code change; defaults
// to the local dev backend so `npm run dev` works out of the box.
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api';

// Requests are deduplicated by URL: concurrent callers for the same URL
// share one in-flight fetch, and a short TTL cache serves repeats that
// land just after the first one resolves (e.g. sibling components each
// calling their own useLiveEtf/useLiveCorrelation/useLiveSectors on the
// same render). This collapses the fan-out of independent hooks into one
// network request per distinct URL without touching any call site.
const CACHE_TTL_MS = 2000;

const cache = new Map(); // url -> { data, expiresAt }
const inFlight = new Map(); // url -> { promise, controller, refCount, abortTimer }

/**
 * Thrown for an HTTP error response, carrying the status so callers can
 * tell a failure that will resolve itself (503 while the backend's data
 * source warms up, 429 rate limiting) from one that never will (404 - no
 * such ETF). A network-level failure still surfaces as fetch()'s own
 * TypeError, which has no status.
 *
 * `retryAfter` (seconds, or null when the response carried none) is the
 * backend's own Retry-After - a lower bound retrySchedule.js's backoff
 * never waits less than, since it can be longer than the schedule would
 * otherwise pick (a rate-limit cooldown, issue #92) and undercutting it
 * would just re-ask before the backend is willing to try upstream again.
 */
export class ApiError extends Error {
  constructor(status, path, retryAfter = null) {
    super(`API ${status}: ${path}`);
    this.name = 'ApiError';
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

/**
 * Whether a failed request is worth re-issuing unchanged.
 *
 * - A TypeError is fetch()'s network-level failure (connection refused,
 *   DNS, CORS) - the signature of a backend that isn't listening yet.
 * - 5xx and 429 are the server saying "not right now": it's up, but a
 *   source behind it isn't (the backend maps its DataUnavailable onto
 *   503), or it's rate limited.
 *
 * Anything else - 404, 400, a bug in the fetcher - is a stable answer
 * that would come back identical however many times it was asked for.
 */
export function isTransientError(err) {
  if (err instanceof TypeError) return true;
  const status = err?.status;
  return status === 429 || (status >= 500 && status < 600);
}

function getCached(url) {
  const entry = cache.get(url);
  if (!entry) return undefined;
  if (Date.now() > entry.expiresAt) {
    cache.delete(url);
    return undefined;
  }
  return entry.data;
}

// Ref-counts callers against the shared in-flight request so one caller's
// abort (e.g. a component unmounting) doesn't cancel the network request
// out from under other callers still waiting on the same URL. Only the
// signal is used to opt out of the shared response — the caller's own
// AbortController still keeps working with useFetch's aborted-check.
function attachSignal(entry, path, signal) {
  if (!signal || signal.aborted) return;

  entry.refCount += 1;
  // Re-attaching before the deferred abort below has fired reclaims the
  // request rather than letting it die.
  if (entry.abortTimer !== null) {
    clearTimeout(entry.abortTimer);
    entry.abortTimer = null;
  }

  signal.addEventListener('abort', () => {
    entry.refCount -= 1;
    if (entry.refCount > 0 || entry.abortTimer !== null) return;

    // Defer the abort by a task instead of cancelling the instant the last
    // caller leaves. A cleanup immediately followed by a re-mount in the
    // same tick — React StrictMode's dev double-invoke, or any rapid
    // remount — then re-attaches to this still-live entry and reuses the
    // request. Aborting synchronously instead meant every request was
    // issued twice in dev: the browser cancelled the first, but the server
    // had already received it and did the work anyway, doubling the very
    // cold-start load that makes the upstream data sources flake.
    entry.abortTimer = setTimeout(() => {
      entry.abortTimer = null;
      if (entry.refCount > 0) return;
      entry.controller.abort();
      // Drop the entry in the same breath as the abort — not just in the
      // fetch's `.finally()`, which only runs once the abort rejection is
      // processed as a microtask. Otherwise a later caller can find this
      // now-dead entry still sitting in `inFlight`, attach to it, and
      // inherit its AbortError even though its own signal was never
      // aborted — surfacing as a false "backend unreachable" for a
      // request that never actually ran, let alone failed.
      if (inFlight.get(path) === entry) inFlight.delete(path);
    }, 0);
  }, { once: true });
}

/**
 * A request's identity, which for a POST is its body as much as its path.
 * Two simulations of different portfolios go to the same URL and are
 * different answers, so the body has to be part of the key that
 * deduplicates and caches them.
 */
function requestKey(path, body) {
  return body === undefined ? path : `POST ${path} ${JSON.stringify(body)}`;
}

async function fetchJson(path, { signal, body } = {}) {
  const key = requestKey(path, body);
  const cached = getCached(key);
  if (cached !== undefined) return cached;

  let entry = inFlight.get(key);
  if (!entry) {
    const controller = new AbortController();
    entry = { controller, refCount: 0, abortTimer: null };
    const init = body === undefined
      ? { signal: controller.signal }
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: controller.signal,
        };
    entry.promise = fetch(`${API_BASE}${path}`, init)
      .then(async (res) => {
        if (!res.ok) {
          const header = res.headers.get('Retry-After');
          const retryAfter = header !== null && Number.isFinite(Number(header))
            ? Number(header)
            : null;
          throw new ApiError(res.status, path, retryAfter);
        }
        const data = await res.json();
        cache.set(key, { data, expiresAt: Date.now() + CACHE_TTL_MS });
        return data;
      })
      .finally(() => {
        if (inFlight.get(key) === entry) inFlight.delete(key);
      });
    inFlight.set(key, entry);
  }

  attachSignal(entry, key, signal);
  return entry.promise;
}

export const api = {
  listEtfs: (opts = {}) => fetchJson('/etfs', opts),
  getEtf: (id, { refresh = false, signal } = {}) =>
    fetchJson(`/etf/${id}${refresh ? '?refresh=true' : ''}`, { signal }),
  getStock: (ticker, opts = {}) => fetchJson(`/stock/${ticker}`, opts),
  getStocks: (tickers, opts = {}) => fetchJson(`/stocks?tickers=${tickers.join(',')}`, opts),
  // Its own request, not a field on getStock above (issue #158): that one
  // is also read by StockPopup and HoldingChartPopup for name/sector/
  // exchange alone, and a description is always a live yfinance call with
  // no DB path, unlike the rest of a stock's metadata — merging it in
  // would make an unrelated Yahoo outage break two popups that never read it.
  getStockDescription: (ticker, opts = {}) => fetchJson(`/stock/${ticker}/description`, opts),
  getSeries: (ticker, period = '1y', interval = '1d', opts = {}) =>
    fetchJson(`/series/${ticker}?period=${period}&interval=${interval}`, opts),
  getCorrelation: (etfId, period = '1y', opts = {}) =>
    fetchJson(`/correlation/${etfId}?period=${period}`, opts),
  getSectors: (etfId, opts = {}) => fetchJson(`/sectors/${etfId}`, opts),

  // When the daily fetch job last finished and when the next run is due
  // (issue #154) — one figure for the whole database, read by the header's
  // Freshness indicator (hooks/useFreshness.js). All three fields null, with
  // a 200, means there is nothing to report; a 503 is retried like any other.
  getFreshness: (opts = {}) => fetchJson('/freshness', opts),

  // Ticker lookup. Search is the as-you-type path and never leaves the
  // tracked universe; resolve is asked once, for a symbol somebody chose,
  // and answers 404 for one that cannot be priced at all.
  searchTickers: (q, { limit, signal } = {}) =>
    fetchJson(`/tickers/search?q=${encodeURIComponent(q)}${limit ? `&limit=${limit}` : ''}`, { signal }),
  resolveTicker: (symbol, opts = {}) =>
    fetchJson(`/tickers/${encodeURIComponent(symbol)}`, opts),

  // Portfolio simulation. A POST because the whole portfolio travels in
  // the body - it is stored in this browser, not on the server, so there
  // is nothing to name in a URL.
  simulatePortfolio: (portfolio, { signal } = {}) =>
    fetchJson('/portfolio/simulate', { signal, body: portfolio }),

  // Portfolio risk (issue #113) — average pairwise correlation, effective
  // bet count and per-holding risk share for the same basket `simulate`
  // takes. Its own endpoint, so a caller fetches it only when a metric
  // that needs it is actually enabled (see usePortfolioRisk.js) rather
  // than paying for it on every simulation.
  getPortfolioRisk: (portfolio, { signal } = {}) =>
    fetchJson('/portfolio/risk', { signal, body: portfolio }),

  // Portfolio metric registry (issue #104) — mirrors the measurement
  // manifest/doc/example endpoints below, for the summary's tiles instead
  // of the table's columns.
  listPortfolioMetrics: (opts = {}) => fetchJson('/portfolio-metrics', opts),
  getPortfolioMetricDoc: (id, opts = {}) =>
    fetchJson(`/portfolio-metric-docs/${encodeURIComponent(id)}`, opts),
  getPortfolioMetricExample: (id, opts = {}) =>
    fetchJson(`/portfolio-metric-docs/${encodeURIComponent(id)}/example`, opts),

  // Fund-level metric values (issue #105) — the computed_from="etf_id"
  // entries in that same registry, scoped by fund rather than by run.
  // The manifest itself is listPortfolioMetrics above; this is only the
  // per-fund values/reasons.
  getFundMetrics: (etfId, opts = {}) =>
    fetchJson(`/portfolio-metrics/${encodeURIComponent(etfId)}`, opts),

  // Measurement plugin system
  listMeasurements: (opts = {}) => fetchJson('/measurements', opts),

  // Measurement documentation. Note the /measurement-docs prefix rather
  // than /measurements/{id}/doc: plugin routes live under the same /api
  // prefix, and /measurements/correlation/{etf_id} would match
  // etf_id="doc" and shadow it.
  getMeasurementDoc: (id, opts = {}) =>
    fetchJson(`/measurement-docs/${encodeURIComponent(id)}`, opts),
  getMeasurementExample: (id, opts = {}) =>
    fetchJson(`/measurement-docs/${encodeURIComponent(id)}/example`, opts),
  runMeasurement: (route, params = {}, { signal } = {}) => {
    let url = route;
    // Replace {etf_id} and other path params
    for (const [key, value] of Object.entries(params)) {
      url = url.replace(`{${key}}`, encodeURIComponent(value));
    }
    // Remaining params become query string
    const queryParams = Object.entries(params)
      .filter(([key]) => !route.includes(`{${key}}`))
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join('&');
    const fullUrl = queryParams ? `${url}?${queryParams}` : url;
    return fetchJson(fullUrl, { signal });
  },
};
