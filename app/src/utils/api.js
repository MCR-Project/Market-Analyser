const API_BASE = 'http://localhost:8000/api';

async function fetchJson(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

export const api = {
  listEtfs: () => fetchJson('/etfs'),
  getEtf: (id, { refresh = false } = {}) => fetchJson(`/etf/${id}${refresh ? '?refresh=true' : ''}`),
  getStock: (ticker) => fetchJson(`/stock/${ticker}`),
  getStocks: (tickers) => fetchJson(`/stocks?tickers=${tickers.join(',')}`),
  getSeries: (ticker, period = '1y', interval = '1d') =>
    fetchJson(`/series/${ticker}?period=${period}&interval=${interval}`),
  getCorrelation: (etfId, period = '1y', threshold = 0) =>
    fetchJson(`/correlation/${etfId}?period=${period}&threshold=${threshold}`),
  getSectors: (etfId) => fetchJson(`/sectors/${etfId}`),

  // Measurement plugin system
  listMeasurements: () => fetchJson('/measurements'),
  runMeasurement: (route, params = {}) => {
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
    return fetchJson(fullUrl);
  },
};
