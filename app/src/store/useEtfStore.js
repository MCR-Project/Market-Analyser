/**
 * useEtfStore — the currently selected ETF ticker, read from and written
 * to the URL.
 *
 * The `/etf/:etfId` route param is the single source of truth for "which
 * ETF is active". Any component can read `etfId` or call `switchEtf`
 * directly, without it being passed down through props. Data hooks
 * (useLiveEtf, etc.) read `etfId` from here instead of owning their own
 * local selection state, so every component that fetches ETF-scoped data
 * — however deep in the tree, and independently of its siblings — always
 * agrees on which ETF is selected.
 *
 * This used to be an in-memory zustand store. Keeping the selection in
 * the URL instead means a reload or a shared link lands on the same ETF,
 * and browser back/forward moves between ETFs, with no extra state to
 * keep in sync: there is only ever one copy of the answer.
 *
 * `switchEtf` preserves whatever view (`/etf/:etfId/:view`) is open, so
 * changing fund from the Matrix tab keeps you on the Matrix tab, and
 * pushes a history entry rather than replacing one — going back returns
 * to the ETF you came from.
 */
import { useCallback } from 'react';
import { useNavigate, useParams } from 'react-router';

/** The ETF `/` redirects to when no fund is named in the URL. */
export const DEFAULT_ETF_ID = 'SPY';

export function useEtfStore() {
  const { etfId, view } = useParams();
  const navigate = useNavigate();

  // Tickers are uppercase everywhere else (the backend uppercases them
  // too), so normalize here rather than letting `/etf/smh` fetch under a
  // second spelling. App redirects the URL itself to the canonical form;
  // this keeps the request correct during the render before that lands.
  const activeEtfId = (etfId || DEFAULT_ETF_ID).toUpperCase();

  const switchEtf = useCallback(
    (id) => navigate(`/etf/${id.toUpperCase()}${view ? `/${view}` : ''}`),
    [navigate, view]
  );

  return { etfId: activeEtfId, switchEtf };
}
