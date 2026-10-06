/**
 * fullViewRoute — the URLs of the Full view (issue #173) and how the rest of the
 * app reads them. Pure, so the one place a path is spelled is the one place it is
 * tested.
 *
 * `/etf/:etfId/full/matrix` and `/etf/:etfId/full/network` are pages of their own,
 * opened in a new tab from the Matrix and Network tabs. They sit under `/etf/`, so
 * the header already calls them "Analyser", but the Analyser tab remembers the last
 * dashboard URL it saw (`AppLayout`) and must not remember one of these: that tab is
 * the way back, and a way back that leads to another Full view is not.
 */

export const FULL_VIEW_KINDS = ['matrix', 'network'];

const FULL_VIEW_PATH = /^\/etf\/([^/]+)\/full\/(matrix|network)$/;

export const fullViewPath = (etfId, kind) => `/etf/${etfId}/full/${kind}`;
export const normalViewPath = (etfId, kind) => `/etf/${etfId}/${kind}`;

/** `{ etfId, kind }` for a Full view URL, else null. */
export function parseFullViewPath(pathname) {
  const match = FULL_VIEW_PATH.exec(pathname);
  return match ? { etfId: match[1], kind: match[2] } : null;
}

/** The dashboard URL the Analyser tab should remember for `pathname`, or null off the dashboard. */
export function dashboardPathOf(pathname, search) {
  const full = parseFullViewPath(pathname);
  if (full) return normalViewPath(full.etfId, full.kind);
  return pathname.startsWith('/etf/') ? pathname + search : null;
}
