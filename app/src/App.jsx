/**
 * App — root shell of the MCR-3 Correlation Dashboard.
 *
 * Rendered inside AppLayout, which owns the shared Header; this is
 * everything below it.
 *
 * Layout (below 2xl, 1536px):
 *  ┌────────────────────────────────────────────┐
 *  │ EtfDashboard  (identity · sector · chart)  │
 *  ├────────────────────────────────────────────┤
 *  │ FundMetricsCard (diversification, etc.)    │
 *  ├────────────────────────────────────────────┤
 *  │ ViewTabs + per-view toolbar                │
 *  ├────────────────────────────────────────────┤
 *  │ TableView: Metrics button + search + table │
 *  │   (columns are dynamic from measurements) │
 *  │ MatrixView + DetailAside                   │
 *  │ NetworkView + DetailAside                  │
 *  └────────────────────────────────────────────┘
 *
 * At 2xl and up the two cards share one row, which hands the active
 * view the height the metrics card used to take (issue #139):
 *  ┌──────────────────────────────┬─────────────┐
 *  │ EtfDashboard                 │ FundMetrics │
 *  ├──────────────────────────────┴─────────────┤
 *  │ ViewTabs + the active view (fills the rest)│
 *  └────────────────────────────────────────────┘
 * The breakpoint is where that row fits with room to spare: the ETF
 * card's three panes need 728px at their minimums (two 280px panes and
 * the 168px sector strip) and are comfortable from about 900px, which at
 * a 2 : 1 split with the metrics card is a 1536px window (the card is
 * 978px there). The content grows to 2352px — a 2400px window less this
 * area's padding — and is centred past that: edge to edge on an
 * ultrawide monitor, a table reads worse than a page with margins. The
 * cap is on the content inside the scrolling area, not on the area
 * itself, so the scrollbar stays at the window's edge.
 *  Overlays: StockPopup, MeasurementPicker, MetricsPicker (fund metrics)
 *  (EtfDashboard owns its own ETF-picker overlay internally)
 *
 * Mounted by main.jsx at /etf/:etfId and /etf/:etfId/:view — the URL is
 * the source of truth for both the fund and the open view, so a reload
 * or a shared link lands on exactly what the sender was looking at.
 */
import { useState, useCallback } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router';
import { useLiveEtf } from './hooks/useLiveEtf';
import { useLiveCorrelation } from './hooks/useLiveCorrelation';
import { useMeasurements } from './hooks/useMeasurements';
import { useMeasurementWindow } from './hooks/useMeasurementWindow';
import { useFundMetrics } from './hooks/useFundMetrics';
import { usePublishLiveStatus } from './hooks/useLiveStatus';
import { EtfDashboard } from './components/etf/EtfDashboard';
import { FundMetricsCard } from './components/etf/FundMetricsCard';
import { StockPopup } from './components/stock/StockPopup';
import { ViewTabs } from './components/ui/ViewTabs';
import { Loading } from './components/ui/Loading';
import { ErrorState } from './components/ui/ErrorState';
import { MeasurementPicker } from './components/ui/MeasurementPicker';
import { MetricsPicker } from './components/ui/MetricsPicker';
import { describeFetchError } from './utils/errorCopy';
import { TableView } from './views/TableView';
import { MatrixView } from './views/MatrixView';
import { NetworkView } from './views/NetworkView';

/** URL slug → tab name in `tabs` below. Also the set of valid slugs. */
const VIEW_BY_SLUG = { table: 'Table', matrix: 'Matrix', network: 'Network' };

export default function App() {
  const { etfId: routeEtfId, view: routeView } = useParams();
  const navigate = useNavigate();
  const { etf, etfId, tickers, weightOf, loading: etfLoading, error: etfError, retry: etfRetry, isLive: etfLive } = useLiveEtf();

  // Shared across Matrix/Network — kept here (rather than inside those
  // now-self-contained views) so the highlighted stock survives switching
  // between the two tabs, since ViewTabs unmounts the inactive one.
  const [selected, setSelected] = useState(null);
  const [stockPopup, setStockPopup] = useState(null);
  const [measurePickerOpen, setMeasurePickerOpen] = useState(false);
  const [fundMetricsPickerOpen, setFundMetricsPickerOpen] = useState(false);

  // This copy is unrelated to NetworkView's own edge-ρ threshold — it's
  // only used for the Header's live badge and StockPopup's peer
  // correlations, neither of which cares about edge filtering.
  const corrData = useLiveCorrelation(etfId);
  const { window: measurementWindow, setWindow: setMeasurementWindow } = useMeasurementWindow();
  const measurements = useMeasurements(etfId, measurementWindow);
  const fundMetrics = useFundMetrics(etfId);

  // The shared Header shows the connectivity badge, but this is the page
  // that knows whether anything actually loaded.
  usePublishLiveStatus(etfLive || corrData.isLive);

  // Reset the matrix/network selection whenever the active ETF changes
  // (from EtfDashboard's own picker, or anywhere else that calls switchEtf).
  // Adjusted during render rather than in an effect — see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  // — so the stale selection never paints for a frame before being cleared.
  const [prevEtfId, setPrevEtfId] = useState(etfId);
  if (etfId !== prevEtfId) {
    setPrevEtfId(etfId);
    setSelected(null);
  }

  // If the manifest fetch failed earlier (e.g. the page loaded before the
  // backend was up), opening the picker re-attempts it — the measurement
  // list is only fetched once otherwise, so this is its recovery path.
  const openMeasurePicker = () => {
    if (measurements.manifest.length === 0) measurements.retryManifest();
    setMeasurePickerOpen(true);
  };

  // Switching tab is a navigation, so each view is linkable and back
  // returns to the previous one.
  const selectView = useCallback(
    (name) => navigate(`/etf/${etfId}/${name.toLowerCase()}`),
    [navigate, etfId]
  );

  // Which tab the URL asks for. No slug at all is legitimate and means
  // Table; an unrecognised slug is not a view, and redirects below.
  const viewFromUrl = routeView ? VIEW_BY_SLUG[routeView.toLowerCase()] : 'Table';
  const activeView = viewFromUrl ?? 'Table';

  // Keep the URL describing what's actually on screen: `/etf/smh` becomes
  // `/etf/SMH`, `/etf/SPY/Matrix` becomes `/etf/SPY/matrix`, and
  // `/etf/SPY/bogus` drops back to the fund's own path rather than
  // leaving the address bar claiming a view that isn't rendered.
  // Replaces rather than pushes, so Back doesn't bounce off the
  // non-canonical URL the user just left.
  const canonicalPath = `/etf/${etfId}${routeView && viewFromUrl ? `/${viewFromUrl.toLowerCase()}` : ''}`;
  const currentPath = `/etf/${routeEtfId}${routeView ? `/${routeView}` : ''}`;
  if (currentPath !== canonicalPath) return <Navigate to={canonicalPath} replace />;

  const tabs = {
    Table: (
      <TableView
        tickers={tickers}
        onSelectStock={setStockPopup}
        measurements={measurements}
        onOpenMeasurePicker={openMeasurePicker}
        measurementWindow={measurementWindow}
        onMeasurementWindowChange={setMeasurementWindow}
      />
    ),
    Matrix: <MatrixView selected={selected} onSelect={setSelected} />,
    Network: <NetworkView selected={selected} onSelect={setSelected} />,
  };

  return (
    <>
      <main className="w-full px-6 pt-6 flex-1 min-h-0 overflow-auto flex flex-col">
        <div className="max-w-[2352px] w-full mx-auto flex-1 min-h-0 flex flex-col">
          {/* Every child below assumes a loaded ETF (non-null etf, populated
              tickers), so the whole main area is gated on that one fetch:
              skeleton while loading, explicit error panel on failure —
              never stale or fabricated data. */}
          {!etf ? (
            etfLoading ? (
              <div className="flex flex-col gap-5 pt-2">
                <Loading variant="bar" />
                <Loading variant="chart" height={180} />
                <Loading variant="skeleton" lines={8} />
              </div>
            ) : (
              <ErrorState
                {...describeFetchError(etfError)}
                onRetry={() => { etfRetry(); measurements.retryManifest(); }}
                className="mt-2"
              />
            )
          ) : (
            <>
              <div className="flex-none flex flex-col 2xl:flex-row 2xl:items-stretch gap-5 mb-5">
                <div className="2xl:flex-[2] min-w-0 flex flex-col">
                  <EtfDashboard />
                </div>
                {/* Renders nothing when no fund metric is registered, and
                    the ETF card then takes the whole row. */}
                <div className="2xl:flex-1 min-w-0 flex flex-col empty:hidden">
                  <FundMetricsCard fundMetrics={fundMetrics} onOpenPicker={() => setFundMetricsPickerOpen(true)} />
                </div>
              </div>

              {/* ── View tabs: each tab owns its own toolbar + content panel ── */}
              <ViewTabs tabs={tabs} active={activeView} onSelect={selectView} />
            </>
          )}
        </div>
      </main>

      {stockPopup && tickers.includes(stockPopup) && (
        <StockPopup ticker={stockPopup} etf={etf} tickers={tickers} weightOf={weightOf} onClose={() => setStockPopup(null)} onNavigate={setStockPopup} corrMatrix={corrData.matrix} corrLoading={corrData.loading} corrIsLive={corrData.isLive} etfLoading={etfLoading} etfIsLive={etfLive} />
      )}

      {measurePickerOpen && (
        <MeasurementPicker manifest={measurements.manifest} activeIds={measurements.activeIds} onToggle={measurements.toggle} onClose={() => setMeasurePickerOpen(false)} />
      )}

      {fundMetricsPickerOpen && (
        <MetricsPicker
          tileMetrics={fundMetrics.tileMetrics}
          families={fundMetrics.families}
          activeIds={fundMetrics.activeIds}
          onToggle={fundMetrics.toggle}
          onClose={() => setFundMetricsPickerOpen(false)}
          eyebrow="FUND METRICS"
          subtitle="Select which tiles to show on the fund metrics card"
          ariaLabel="Fund metrics"
          emptyText="No fund metrics available — is the backend running?"
        />
      )}
    </>
  );
}
