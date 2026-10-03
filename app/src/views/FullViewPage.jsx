/**
 * FullViewPage — the whole-fund correlation matrix or network of a deep-filled
 * ETF, on a page of its own (issue #173).
 *
 * Mounted at `/etf/:etfId/full/matrix` and `/etf/:etfId/full/network` and opened in
 * a new tab from the Matrix and Network tabs. It is drawn from the result the
 * Deep-fill finished with (`GET /api/deep-fill/{id}/full-view`) — read back, not
 * recomputed — so what it says as of is the Deep-fill's own time, and it never mixes
 * in data from the normal view. If that result does not exist (never run, expired, or
 * the job is still going) the page says so and links back; it never draws a partial
 * picture.
 *
 *   ┌────────────────────────────────────────────────────┐
 *   │ ← SPY Matrix   SPY · Full matrix        Matrix|Net │  header (FullViewHeader)
 *   │ Past year · 458 holdings drawn · as of … · until … │
 *   ├────────────────────────────────────────────────────┤
 *   │ order Cluster|A–Z|Weight  within …    selection    │  the drawing's own controls
 *   ├────────────────────────────────────────────────────┤
 *   │                                                    │
 *   │      canvas: a square, as wide as the page         │
 *   │                                                    │
 *   ├────────────────────────────────────────────────────┤
 *   │ legend and gestures                                │
 *   └────────────────────────────────────────────────────┘
 *
 * View state is in the URL like the rest of the app: `?matrixOrder=` and
 * `?matrixWithin=` (the normal matrix's own keys and defaults — `utils/matrixOrder.js`
 * decides the order) and `?threshold=` for the network. The selected stock is not:
 * it is a way of looking, as on the normal views.
 */
import { useMemo, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router';
import { useFetch } from '../hooks/useFetch';
import { useFullNetworkLayout } from '../hooks/useFullNetworkLayout';
import { useFullViewThreshold } from '../hooks/useFullViewThreshold';
import { useMatrixOrder } from '../hooks/useMatrixOrder';
import { usePublishLiveStatus } from '../hooks/useLiveStatus';
import { api } from '../utils/api';
import { describeFetchError } from '../utils/errorCopy';
import { fmtCorr } from '../utils/format';
import { decodeFullView, fmtWeight } from '../utils/fullView';
import { THRESHOLD_MIN, THRESHOLD_MAX, THRESHOLD_STEP, rankedLinks, linksAtLeast } from '../utils/fullNetwork';
import { describeClusters } from '../utils/clusters';
import { ORDER_OPTIONS, WITHIN_OPTIONS } from '../utils/matrixOrder';
import { normalViewPath } from '../utils/fullViewRoute';
import { useCanvasColors } from '../components/fullview/canvasColors';
import { FullMatrix } from '../components/fullview/FullMatrix';
import { FullNetwork } from '../components/fullview/FullNetwork';
import { FullViewHeader } from '../components/fullview/FullViewHeader';
import { Panel } from '../components/fullview/Panel';
import { ErrorState } from '../components/ui/ErrorState';
import { Loading } from '../components/ui/Loading';
import { SegmentedControl } from '../components/ui/SegmentedControl';

export function FullViewPage({ kind }) {
  const { etfId: routeId } = useParams();
  const etfId = routeId.toUpperCase();

  const { data, loading, error, retry } = useFetch(
    (signal) => api.getFullView(etfId, { signal }),
    [etfId],
    { fallback: null }
  );

  // A payload whose parts disagree is not drawn (utils/fullView.js): a matrix read
  // at the wrong stride is plausible and wrong.
  const decoded = useMemo(() => {
    if (!data) return { fund: null, unreadable: false };
    try {
      return { fund: decodeFullView(data), unreadable: false };
    } catch (err) {
      console.warn('[FullViewPage]', err.message);
      return { fund: null, unreadable: true };
    }
  }, [data]);

  usePublishLiveStatus(!!decoded.fund);

  if (routeId !== etfId) return <Navigate to={`/etf/${etfId}/full/${kind}`} replace />;

  let body;
  if (decoded.fund) {
    // Keyed by the result, so a fresh Deep-fill starts with no stock selected.
    body = <FullViewBody key={`${decoded.fund.etfId}:${decoded.fund.asOf}`} fund={decoded.fund} kind={kind} />;
  } else if (loading) {
    body = (
      <div className="flex flex-col gap-4 pt-2">
        <Loading variant="bar" />
        <Loading variant="chart" height={480} />
      </div>
    );
  } else if (error?.status === 404) {
    body = <NotDeepFilled etfId={etfId} kind={kind} />;
  } else if (decoded.unreadable) {
    body = (
      <ErrorState
        title="This result could not be read"
        message="The server's answer did not hold together, so nothing is drawn rather than something wrong. Try again; if it keeps happening, run the Deep-fill again."
        onRetry={retry}
        className="mt-2"
      />
    );
  } else {
    body = <ErrorState {...describeFetchError(error)} onRetry={retry} className="mt-2" />;
  }

  return (
    <main className="w-full px-6 pt-6 pb-6 flex-1 min-h-0 overflow-auto [scrollbar-gutter:stable] flex flex-col gap-4">
      {body}
    </main>
  );
}

/** What a Full view says when there is nothing to draw: no result, which is not an error. */
function NotDeepFilled({ etfId, kind }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 px-6 text-center bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] mt-2">
      <div className="text-base font-bold text-[var(--fg)]">{etfId} is not deep-filled right now</div>
      <p className="text-sm text-[var(--fg-2)] leading-relaxed m-0 max-w-[520px]">
        Either no Deep-fill has been run for this fund, or the one that was has expired — the
        server keeps a result for a limited time and then goes back to the fund&apos;s tracked
        holdings. The Full view only ever shows a finished Deep-fill, never a partial one. Start
        one from the fund&apos;s page.
      </p>
      <Link
        to={normalViewPath(etfId, kind)}
        className="mt-1 px-4 py-2 text-sm font-semibold text-[var(--accent)] no-underline bg-[var(--accent-soft)] border border-[var(--accent-ring)] rounded-[var(--radius-md)] transition-colors duration-150 hover:bg-[var(--accent-ring)]"
      >
        Back to {etfId}
      </Link>
    </div>
  );
}

function FullViewBody({ fund, kind }) {
  const [selected, setSelected] = useState(null);
  const [hostRef, colors] = useCanvasColors();
  const { clusterOf } = useMemo(() => describeClusters(fund.holdings, fund.clusters), [fund]);
  const Drawing = kind === 'matrix' ? MatrixBody : NetworkBody;

  return (
    <>
      <FullViewHeader fund={fund} kind={kind} />
      <Drawing
        fund={fund} selected={selected} onSelect={setSelected}
        colors={colors} hostRef={hostRef} clusterOf={clusterOf}
      />
    </>
  );
}

// ── Matrix ────────────────────────────────────────────────────────────────────

function MatrixBody({ fund, selected, onSelect, colors, hostRef, clusterOf }) {
  const { order, within, setOrder, setWithin } = useMatrixOrder();
  return (
    <>
      <div className="flex-none flex items-center gap-x-4 gap-y-2 flex-wrap">
        <SegmentedControl label="order" options={ORDER_OPTIONS} value={order} onChange={setOrder} />
        {order === 'cluster' && (
          <SegmentedControl label="within" options={WITHIN_OPTIONS} value={within} onChange={setWithin} />
        )}
        <Selection fund={fund} selected={selected} clusterOf={clusterOf} onClear={() => onSelect(null)} />
      </div>
      <Stage hostRef={hostRef}>
        {colors && (
          <FullMatrix fund={fund} order={order} within={within} selected={selected} onSelect={onSelect} colors={colors} />
        )}
        <Legend>
          <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-2)]">CORRELATION</span>
          <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">0.0</span>
          <div className="w-[160px] h-2 rounded-full border border-[var(--border)]" style={{ background: 'linear-gradient(90deg, var(--bg-1), color-mix(in oklab, var(--accent) 92%, var(--bg-1)))' }} />
          <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">1.0</span>
          <span className="flex items-center gap-1.5 text-xs text-[var(--fg-3)]">
            <span className="w-3 h-3 rounded-[2px] bg-[var(--bg-3)] border border-[var(--border)]" aria-hidden="true" />
            no correlation computed
          </span>
          <span className="text-xs text-[var(--fg-3)]">
            Pearson ρ of daily returns · outlined blocks are clusters, not sectors · scroll or pinch to zoom, drag to pan, click a stock to outline its row and column
          </span>
        </Legend>
      </Stage>
    </>
  );
}

// ── Network ───────────────────────────────────────────────────────────────────

function NetworkBody({ fund, selected, onSelect, colors, hostRef, clusterOf }) {
  const { threshold, setThreshold } = useFullViewThreshold();
  const { positions, error } = useFullNetworkLayout(fund);
  // Collected once per result: the links worth ever drawing, strongest first, so the
  // threshold below is a search of this list and never another pass over the matrix.
  const ranked = useMemo(() => rankedLinks(fund.corr, fund.n, THRESHOLD_MIN), [fund]);
  const links = linksAtLeast(ranked, threshold);

  return (
    <>
      <div className="flex-none flex items-center gap-x-3 gap-y-2 flex-wrap">
        <label htmlFor="full-threshold" className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">link threshold ρ ≥</label>
        <input
          id="full-threshold"
          type="range"
          className="corr-range flex-1 max-w-[300px]"
          min={THRESHOLD_MIN}
          max={THRESHOLD_MAX}
          step={THRESHOLD_STEP}
          value={threshold}
          onChange={(e) => setThreshold(parseFloat(e.target.value))}
        />
        <span className="font-[var(--font-mono)] text-[13px] font-semibold text-[var(--fg)] w-9 tabular-nums">{fmtCorr(threshold)}</span>
        <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)] tabular-nums">· {links.toLocaleString()} links</span>
        <Selection fund={fund} selected={selected} clusterOf={clusterOf} onClear={() => onSelect(null)} />
      </div>

      <Stage hostRef={hostRef}>
        {error ? (
          <Notice>The layout could not be worked out ({error.message}). Reload to try again.</Notice>
        ) : !positions ? (
          <Notice busy>Laying out {fund.n} holdings…</Notice>
        ) : colors ? (
          <FullNetwork
            fund={fund} positions={positions} ranked={ranked} threshold={threshold}
            selected={selected} onSelect={onSelect} colors={colors}
          />
        ) : null}
        <Legend>
          <span className="flex items-center gap-[7px] text-xs text-[var(--fg-2)]"><span className="w-3.5 h-3.5 rounded-full bg-[var(--bg-2)] border-[1.5px] border-[var(--border-strong)]" />node size = weight in fund</span>
          <span className="flex items-center gap-[7px] text-xs text-[var(--fg-2)]"><span className="w-[22px] h-[3px] rounded-full bg-[var(--accent)]" />line = correlation strength</span>
          <span className="text-xs text-[var(--fg-3)]">scroll or pinch to zoom, drag to pan, click a node to isolate its links</span>
        </Legend>
      </Stage>
    </>
  );
}

// ── Shared pieces ─────────────────────────────────────────────────────────────

/** What a drawing sits in: the square panel, full width, and the legend under it. Not
 *  allowed to shrink: the page scrolls to reach it rather than squeezing the picture. */
function Stage({ hostRef, children }) {
  return (
    <section ref={hostRef} className="flex-none flex flex-col gap-3">
      {children}
    </section>
  );
}

function Legend({ children }) {
  return (
    <div className="flex items-center gap-x-6 gap-y-2 flex-wrap px-1">
      {children}
    </div>
  );
}

/** A message in the same square a drawing would fill, so the page does not jump when it arrives. */
function Notice({ busy = false, children }) {
  return (
    <Panel className="grid place-items-center text-sm text-[var(--fg-2)]">
      <span className="flex items-center gap-3" role="status">
        {busy && <span className="w-5 h-5 rounded-full border-2 border-[var(--border-strong)] border-t-[var(--accent)] animate-spin" aria-hidden="true" />}
        {children}
      </span>
    </Panel>
  );
}

/** What the selected stock is, in a line, with the way to clear it. */
function Selection({ fund, selected, clusterOf, onClear }) {
  if (selected == null) {
    return <span className="font-[var(--font-mono)] text-xs text-[var(--fg-3)]">click a stock to select it</span>;
  }
  const i = fund.indexOf.get(selected);
  const average = fund.averages[selected];
  return (
    <span className="flex items-center gap-2 font-[var(--font-mono)] text-xs text-[var(--fg-1)]">
      <span className="font-bold text-[var(--accent)]">{selected}</span>
      <span>{fmtWeight(fund.weights[i])} of the fund</span>
      {clusterOf[selected] && <span>· {clusterOf[selected].name}</span>}
      {average != null && <span>· avg ρ {fmtCorr(average)}</span>}
      <button
        type="button"
        onClick={onClear}
        className="px-2 py-0.5 text-[11px] text-[var(--fg-2)] bg-transparent border border-[var(--border-strong)] rounded-full cursor-pointer hover:bg-[var(--bg-2)]"
      >
        clear
      </button>
    </span>
  );
}
