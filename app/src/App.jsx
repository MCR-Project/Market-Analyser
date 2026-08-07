/**
 * App — root shell of the MCR-3 Correlation Dashboard.
 *
 * Layout:
 *  ┌────────────────────────────────────────────┐
 *  │ Header  (nav, connectivity badge, theme)   │
 *  ├────────────────────────────────────────────┤
 *  │ EtfDashboard  (identity · sector · chart)  │
 *  ├────────────────────────────────────────────┤
 *  │ ViewTabs + per-view toolbar                │
 *  ├────────────────────────────────────────────┤
 *  │ TableView: Metrics button + search + table │
 *  │   (columns are dynamic from measurements) │
 *  │ MatrixView + DetailAside                   │
 *  │ NetworkView + DetailAside                  │
 *  └────────────────────────────────────────────┘
 *  Overlays: StockPopup, MeasurementPicker
 *  (EtfDashboard owns its own ETF-picker overlay internally)
 */
import { useState, useEffect } from 'react';
import { useTheme } from './hooks/useTheme';
import { useLiveEtf } from './hooks/useLiveEtf';
import { useLiveCorrelation } from './hooks/useLiveCorrelation';
import { useMeasurements } from './hooks/useMeasurements';
import { Header } from './components/layout/Header';
import { EtfDashboard } from './components/etf/EtfDashboard';
import { StockPopup } from './components/stock/StockPopup';
import { ViewTabs } from './components/ui/ViewTabs';
import { Loading } from './components/ui/Loading';
import { ErrorState } from './components/ui/ErrorState';
import { MeasurementPicker } from './components/ui/MeasurementPicker';
import { TableView } from './views/TableView';
import { MatrixView } from './views/MatrixView';
import { NetworkView } from './views/NetworkView';

export default function App() {
  const { theme, toggleTheme } = useTheme('light');
  const { etf, etfId, tickers, weightOf, loading: etfLoading, retry: etfRetry, isLive: etfLive } = useLiveEtf();

  // Shared across Matrix/Network — kept here (rather than inside those
  // now-self-contained views) so the highlighted stock survives switching
  // between the two tabs, since ViewTabs unmounts the inactive one.
  const [selected, setSelected] = useState(null);
  const [stockPopup, setStockPopup] = useState(null);
  const [measurePickerOpen, setMeasurePickerOpen] = useState(false);

  // threshold=0 here is unrelated to NetworkView's own edge-ρ threshold —
  // this copy is only used for the Header's live badge and StockPopup's
  // peer correlations, neither of which cares about edge filtering.
  const corrData = useLiveCorrelation(etfId, tickers, 0);
  const measurements = useMeasurements(etfId);

  // Reset the matrix/network selection whenever the active ETF changes
  // (from EtfDashboard's own picker, or anywhere else that calls switchEtf).
  useEffect(() => {
    setSelected(null);
  }, [etfId]);

  // If the manifest fetch failed earlier (e.g. the page loaded before the
  // backend was up), opening the picker re-attempts it — the measurement
  // list is only fetched once otherwise, so this is its recovery path.
  const openMeasurePicker = () => {
    if (measurements.manifest.length === 0) measurements.retryManifest();
    setMeasurePickerOpen(true);
  };

  const tabs = {
    Table: (
      <TableView
        etf={etf}
        tickers={tickers}
        onSelectStock={setStockPopup}
        measurements={measurements}
        onOpenMeasurePicker={openMeasurePicker}
      />
    ),
    Matrix: <MatrixView selected={selected} onSelect={setSelected} />,
    Network: <NetworkView selected={selected} onSelect={setSelected} />,
  };

  return (
    <div className="h-screen overflow-hidden flex flex-col bg-[var(--bg)] text-[var(--fg-1)] font-[var(--font-body)]">
      <Header theme={theme} onToggleTheme={toggleTheme} isLive={etfLive || corrData.isLive} />

      <main className="max-w-[1280px] w-full mx-auto px-6 pt-6 flex-1 min-h-0 overflow-auto flex flex-col">
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
            <ErrorState onRetry={() => { etfRetry(); measurements.retryManifest(); }} className="mt-2" />
          )
        ) : (
          <>
            <EtfDashboard />

            {/* ── View tabs: each tab owns its own toolbar + content panel ── */}
            <ViewTabs tabs={tabs} />
          </>
        )}
      </main>

      {stockPopup && tickers.includes(stockPopup) && (
        <StockPopup ticker={stockPopup} etf={etf} tickers={tickers} weightOf={weightOf} onClose={() => setStockPopup(null)} onNavigate={setStockPopup} corrMatrix={corrData.matrix} corrLoading={corrData.loading} corrIsLive={corrData.isLive} etfLoading={etfLoading} etfIsLive={etfLive} />
      )}

      {measurePickerOpen && (
        <MeasurementPicker manifest={measurements.manifest} activeIds={measurements.activeIds} onToggle={measurements.toggle} onClose={() => setMeasurePickerOpen(false)} />
      )}
    </div>
  );
}
