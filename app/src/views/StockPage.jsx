/**
 * StockPage — browse one stock on its own (issue #158): a real price chart
 * with a candle/line toggle, its business description, metric tiles scored
 * against a $100 Benchmark-style Run (#159), and comparing a second stock
 * (#160). Never more than two stocks at once — the primary plus one.
 *
 *  ┌────────────────┬─────────────────────────────┐
 *  │ filter history │  [ search a stock…        ]  │ ← fades on scroll
 *  │ NVDA           │  NVDA  NVIDIA Corporation    │
 *  │ TSLA           │  Technology · NASDAQ         │
 *  │ …              │                              │
 *  │                │  [ compare against… ]        │
 *  │                │  1W 1M 1Y 5Y      [candles]  │
 *  │                │  ┌────────────────────────┐  │
 *  │                │  │      price chart        │  │  ← ComparisonChart
 *  │                │  └────────────────────────┘  │    while comparing
 *  │                │  Metrics …                   │  ← ComparisonSummary
 *  │                │  About                       │    while comparing
 *  │                │  <business description>      │
 *  └────────────────┴─────────────────────────────┘
 *
 * Two different search boxes, two different jobs. The sidebar's
 * (StocksSidebar) only filters the recently-viewed list already on
 * screen — it never calls the API. The one that actually switches stocks
 * lives here, in the main column, and is always mounted (so it works from
 * the empty landing state, an error state, or mid-browse) but only
 * *visible* at the top of the scroll: it fades out on scrolling down and
 * back in on scrolling up, `useScrollFade` below, rather than permanently
 * occupying space above a 280px chart most of the page doesn't need it
 * once already open. The compare-against control (issue #160,
 * `useStockComparison`) is a third, distinct one, inside the Performance
 * card, above the graph — it only ever adds a second line to the chart and
 * the Metrics card, never switches which stock the page itself is about,
 * and its own visit is never recorded in the recently-viewed sidebar
 * (only a resolve of the *primary* ticker, below, calls `visit`).
 *
 * /stock          → nothing open yet, sidebar usable, empty landing state
 * /stock/:ticker  → one stock, resolved the same way a portfolio holding
 *                   is (api.resolveTicker) — the gate that tells a real
 *                   but untracked symbol apart from a typo, and the one
 *                   place this page learns whether what was typed is
 *                   actually a tracked ETF, in which case it hands off to
 *                   /etf/:etfId instead rather than rendering it here
 *                   (docs/adr/0004-untracked-symbols-on-the-stock-page-are-treated-as-stocks.md).
 *
 * The resolve fetch is kept in this component, but the price series
 * (`useLiveSeries`) and the description fetch live in the `StockDetail`
 * child below, mounted only once a ticker has actually resolved — a
 * `useLiveSeries` call with no ticker would still fire a request for one,
 * since that hook has no "disabled" switch of its own (it is shared with
 * StockPopup and HoldingChartPopup, which always have a real ticker by the
 * time either mounts).
 *
 * A resolved, non-ETF visit is recorded in the recently-viewed sidebar
 * (store/recentStocks.js) the moment it resolves — not before, so a typo'd
 * URL never earns a place in the list.
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router';
import { useFetch } from '../hooks/useFetch';
import { useLiveSeries } from '../hooks/useLiveSeries';
import { useRecentStocks } from '../hooks/useRecentStocks';
import { useSimulationWindow } from '../hooks/useSimulationWindow';
import { usePortfolioSimulation } from '../hooks/usePortfolioSimulation';
import { useStockMetrics } from '../hooks/useStockMetrics';
import { useStockComparison } from '../hooks/useStockComparison';
import { useComparisonRuns } from '../hooks/useComparisonRuns';
import { api } from '../utils/api';
import { PriceChart } from '../components/charts/PriceChart';
import { CandleToggle } from '../components/charts/CandleToggle';
import { TimeframeTabs } from '../components/ui/TimeframeTabs';
import { Loading } from '../components/ui/Loading';
import { ErrorState } from '../components/ui/ErrorState';
import { MetricsPicker } from '../components/ui/MetricsPicker';
import { ComparisonChart } from '../components/portfolio/ComparisonChart';
import { describeFetchError } from '../utils/errorCopy';
import { Logo } from '../components/ui/Logo';
import { StocksSidebar } from '../components/stock/StocksSidebar';
import { StockMetricsCard } from '../components/stock/StockMetricsCard';
import { TickerSearchField } from '../components/portfolio/TickerSearchField';

const VALID_TIMEFRAMES = ['1W', '1M', '1Y', '5Y'];

// The opening amount every Stock page Run is simulated with (issue #159).
// There is no open Portfolio to borrow a real amount from the way a
// Benchmark on the portfolio page does, so this is a fixed "growth of
// $100" baseline instead — CONTEXT.md's Benchmark entry states the same
// reasoning. Dollar-denominated tiles (final value, gain) read against
// this rather than a user-chosen investment.
const STOCK_RUN_AMOUNT = 100;

// How far the scroll position has to move, in either direction, before the
// search bar reacts — a few pixels of noise (trackpad settling, a resize
// reflow) must not flicker it, but a deliberate scroll should feel instant.
const SCROLL_FADE_SLACK = 4;
// Always shown within this many pixels of the top, so landing on the page
// (or scrolling all the way back) never leaves it ambiguously mid-fade.
const SCROLL_FADE_TOP_ZONE = 8;

export function StockPage() {
  const { ticker: rawTicker } = useParams();
  const ticker = rawTicker ? rawTicker.toUpperCase() : null;
  const navigate = useNavigate();
  const [tickers, visit] = useRecentStocks();

  // The gate: confirms the symbol can actually be priced (a typo answers
  // 404, same as everywhere else a ticker is chosen), and is what tells a
  // tracked ETF apart from a stock — get_stock_info alone can't, it has no
  // notion of the tracked universe at all.
  const {
    data: resolved,
    loading: resolveLoading,
    error: resolveError,
    retry: retryResolve,
  } = useFetch(
    (signal) => (ticker ? api.resolveTicker(ticker, { signal }) : Promise.resolve(null)),
    [ticker],
    { fallback: null }
  );

  const isEtf = resolved?.kind === 'etf';
  const resolvedSymbol = resolved?.symbol ?? null;

  useEffect(() => {
    if (resolvedSymbol && !isEtf) visit(resolvedSymbol);
  }, [resolvedSymbol, isEtf, visit]);

  const handleResolved = (result) => {
    navigate(result.kind === 'etf' ? `/etf/${result.symbol}` : `/stock/${result.symbol}`);
  };

  const [searchVisible, onMainScroll] = useScrollFade();

  if (isEtf) return <Navigate to={`/etf/${resolved.symbol}`} replace />;
  // Canonicalise rather than error (App.jsx does the same for /etf/smh):
  // resolve_ticker always normalises to uppercase, so this only fires for
  // whatever `ticker.toUpperCase()` above didn't already cover.
  if (resolved && resolved.symbol !== ticker) {
    return <Navigate to={`/stock/${resolved.symbol}`} replace />;
  }

  return (
    <div className="flex-1 min-h-0 flex">
      <aside className="flex-none w-[264px] border-r border-[var(--border)] p-4 min-h-0">
        <StocksSidebar tickers={tickers} />
      </aside>

      <main className="corr-scroll flex-1 min-w-0 overflow-y-auto px-8 py-8" onScroll={onMainScroll}>
        <div className="max-w-[900px] mx-auto flex flex-col gap-6">
          <div
            className="sticky top-0 z-10 -mx-8 transition-all duration-500 ease-out"
            style={{
              opacity: searchVisible ? 1 : 0,
              transform: searchVisible ? 'translateY(10px)' : 'translateY(-10px)',
              pointerEvents: searchVisible ? 'auto' : 'none',
            }}
          >
            <TickerSearchField
              placeholder="Search a stock…"
              ariaLabel="Search for a stock"
              disabled={!searchVisible}
              onResolved={handleResolved}
            />
          </div>

          {!ticker ? (
            <EmptyState />
          ) : resolveError ? (
            <ErrorState {...describeFetchError(resolveError)} onRetry={retryResolve} />
          ) : resolveLoading || !resolved ? (
            <Loading variant="skeleton" lines={4} />
          ) : (
            <StockDetail resolved={resolved} />
          )}
        </div>
      </main>
    </div>
  );
}

/** `[visible, onScroll]`: whether the sticky search bar should show, and
 *  the scroll handler that decides it. Always visible within
 *  SCROLL_FADE_TOP_ZONE of the top; past that, it hides on a scroll down
 *  of more than SCROLL_FADE_SLACK and reappears on a scroll up of the
 *  same, so a stray pixel of jitter from a trackpad or a layout reflow
 *  can't flip it back and forth. Reads `main`'s own scrollTop (the page
 *  has no window-level scroll — `main` is the scrolling element), so this
 *  is plain state plus a ref, not something worth a store module: it
 *  touches the DOM directly and has nothing to say once this component is
 *  gone. */
function useScrollFade() {
  const [visible, setVisible] = useState(true);
  const lastTop = useRef(0);

  const onScroll = useCallback((event) => {
    const top = event.currentTarget.scrollTop;
    const last = lastTop.current;
    if (top <= SCROLL_FADE_TOP_ZONE) setVisible(true);
    else if (top > last + SCROLL_FADE_SLACK) setVisible(false);
    else if (top < last - SCROLL_FADE_SLACK) setVisible(true);
    lastTop.current = top;
  }, []);

  return [visible, onScroll];
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-24 text-center">
      <p className="text-[15px] font-semibold text-[var(--fg)] m-0">
        Search for a stock to begin
      </p>
      <p className="text-[13px] text-[var(--fg-2)] m-0 max-w-[360px]">
        Its price chart and business description will show up here.
      </p>
    </div>
  );
}

/** Everything below the resolve gate: the header, the price chart and the
 *  description. Mounted only once `resolved` names a real, non-ETF ticker,
 *  so useLiveSeries never fires for an empty or not-yet-resolved one. */
const StockDetail = memo(function StockDetail({ resolved }) {
  const ticker = resolved.symbol;
  const [timeframe, setTimeframe] = useTimeframeParam();
  const [metricsPickerOpen, setMetricsPickerOpen] = useState(false);

  // The Run this stock is scored against (issue #159): a basket of one,
  // 100% weighted, no schedule — the standalone-page reading of Benchmark
  // (CONTEXT.md), simulated exactly like a portfolio's own run so the
  // whole portfolio_metrics registry applies unchanged. Memoised so a
  // render that doesn't change `ticker` doesn't hand usePortfolioSimulation
  // a new object identity for no reason — it stringifies this every
  // render regardless, but there's no reason to make that string differ.
  const syntheticPortfolio = useMemo(() => ({
    holdings: [{ ticker, weight: 100 }],
    value: STOCK_RUN_AMOUNT,
    rebalance: 'none',
  }), [ticker]);

  const windowState = useSimulationWindow();
  const {
    simulation,
    loading: runLoading,
    error: runError,
    stale: runStale,
    retry: retryRun,
  } = usePortfolioSimulation(syntheticPortfolio, windowState.request);

  const stockMetrics = useStockMetrics();

  // Comparing a second stock (issue #160). `usePortfolioSimulation` above
  // keeps scoring the primary alone regardless — the same "both hooks
  // always run" shape PortfolioPanel.jsx already uses between its own
  // usePortfolioSimulation and useComparisonRuns — so nothing here can
  // change which hooks a render calls, only what `lines` (and so what
  // gets fetched) contains. `lines` is empty, not the primary alone, while
  // nothing is being compared: useComparisonRuns already treats an empty
  // list as "nothing to fetch" (see its own module docstring), so this
  // costs nothing extra until a second stock is actually set.
  const comparison = useStockComparison(ticker);
  const comparisonLines = useMemo(() => {
    if (!comparison.compareTicker) return [];
    const lineFor = (symbol) => ({
      key: symbol,
      label: symbol,
      kind: 'stock',
      request: {
        holdings: [{ ticker: symbol, weight: 100 }],
        value: STOCK_RUN_AMOUNT,
        rebalance: 'none',
        ...windowState.request,
      },
    });
    return [lineFor(ticker), lineFor(comparison.compareTicker)];
  }, [ticker, comparison.compareTicker, windowState.request]);
  const comparisonRuns = useComparisonRuns(comparisonLines);
  // Memoised so StockMetricsCard's own memo() isn't defeated by a fresh
  // object literal on every StockDetail render (e.g. info/description
  // resolving, the picker opening) that doesn't actually change what
  // this prop describes.
  const stockMetricsComparison = useMemo(
    () => (comparison.compareTicker ? { runs: comparisonRuns.runs, stale: comparisonRuns.stale } : null),
    [comparison.compareTicker, comparisonRuns.runs, comparisonRuns.stale]
  );

  const { data: info, loading: infoLoading } = useFetch(
    (signal) => api.getStock(ticker, { signal }),
    [ticker],
    { fallback: null }
  );

  // Its own request, not folded into `info` above: a description is
  // always a live yfinance call with no DB path (get_stock_description's
  // own docstring), so it is slower and more likely to fail than the rest
  // of this header — a separate loading/error state keeps a live-data
  // hiccup on the description from blanking out the name/sector that
  // already loaded successfully.
  const {
    data: descriptionData,
    loading: descriptionLoading,
    error: descriptionError,
    retry: retryDescription,
  } = useFetch(
    (signal) => api.getStockDescription(ticker, { signal }),
    [ticker],
    { fallback: null }
  );

  return (
    <>
      {/* Header — its own card, the same bg-1/border/radius-lg/shadow-sm
          treatment FundMetricsCard already uses, so every section here
          reads as a distinct panel rather than loose content floating on
          the page background. */}
      <section className="bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] p-5">
        <div className="flex items-start gap-4">
          <Logo ticker={ticker} name={info?.name} size={48} />
          <div className="flex flex-col gap-1.5 min-w-0">
            <div className="flex items-baseline gap-3 flex-wrap">
              <span className="font-[var(--font-mono)] text-[26px] font-extrabold text-[var(--accent)] tracking-tight leading-none">
                {ticker}
              </span>
              {infoLoading ? (
                <Loading variant="skeleton" lines={1} className="w-40" />
              ) : (
                <span className="text-[17px] font-semibold text-[var(--fg)] tracking-tight">
                  {info?.name || resolved.name || ticker}
                </span>
              )}
            </div>
            <div className="flex items-center gap-[7px] flex-wrap">
              {!infoLoading && info?.sector && (
                <span className="text-xs text-[var(--fg-2)] bg-[var(--bg-3)] rounded-full py-[3px] px-2.5">
                  {info.sector}
                </span>
              )}
              {!infoLoading && info?.exchange && (
                <span className="text-[11px] text-[var(--fg-3)] bg-[var(--bg-3)] rounded-full py-0.5 px-2.5 font-[var(--font-mono)]">
                  {info.exchange}
                </span>
              )}
              {!resolved.tracked && (
                <span className="text-[11px] text-[var(--fg-3)] bg-[var(--bg-3)] rounded-full py-0.5 px-2.5">
                  Not tracked here — priced live
                </span>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Performance */}
      <section className="bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] p-5 flex flex-col gap-3">
        {/* Compare against… (issue #160) — its own control, above the
            graph, distinct from the page's primary search bar: that one
            switches which stock the whole page is about, this one only
            adds a second line to this chart and the Metrics card below.
            Capped at one compare ticker by useStockComparison's own data
            model, not just by this control only ever offering one slot. */}
        <div className="flex items-center gap-2">
          {comparison.compareTicker ? (
            <div className="flex items-center gap-2 h-[38px] px-3 bg-[var(--bg-3)] rounded-[var(--radius-md)]">
              <span className="text-[12px] text-[var(--fg-2)]">Comparing against</span>
              <span className="font-[var(--font-mono)] text-[12.5px] font-bold text-[var(--accent)]">
                {comparison.compareTicker}
              </span>
              <button
                onClick={comparison.clearCompare}
                aria-label={`Stop comparing against ${comparison.compareTicker}`}
                className="w-5 h-5 grid place-items-center rounded-full bg-transparent border-none cursor-pointer text-[var(--fg-2)] hover:text-[var(--fg)]"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="m18 6-12 12M6 6l12 12" /></svg>
              </button>
            </div>
          ) : (
            <TickerSearchField
              placeholder="Compare against…"
              ariaLabel="Compare against another stock"
              exclude={[ticker]}
              onResolved={(result) => comparison.setCompare(result.symbol)}
              className="w-full max-w-[260px]"
            />
          )}
        </div>

        {comparison.compareTicker ? (
          comparisonRuns.runs ? (
            <ComparisonChart runs={comparisonRuns.runs} stale={comparisonRuns.stale} />
          ) : (
            <p className="text-[12px] text-[var(--fg-2)] m-0">Simulating each line…</p>
          )
        ) : (
          <PricePerformance ticker={ticker} timeframe={timeframe} onTimeframeChange={setTimeframe} />
        )}
      </section>

      {/* Metrics (issue #159) — scored against the basket-of-one Run
          above, over this card's own window, independent of the
          Performance chart's own ?tf= timeframe. Swaps to a side-by-side
          comparison (issue #160) the same moment the chart above does. */}
      <StockMetricsCard
        windowState={windowState}
        metrics={simulation?.metrics}
        resolvedStart={simulation?.start || null}
        resolvedEnd={simulation?.end || null}
        loading={runLoading}
        stale={runStale}
        error={runError}
        onRetry={retryRun}
        tileMetrics={stockMetrics.tileMetrics}
        activeIds={stockMetrics.activeIds}
        onOpenPicker={() => setMetricsPickerOpen(true)}
        comparison={stockMetricsComparison}
      />

      {metricsPickerOpen && (
        <MetricsPicker
          tileMetrics={stockMetrics.tileMetrics}
          families={stockMetrics.families}
          activeIds={stockMetrics.activeIds}
          onToggle={stockMetrics.toggle}
          onClose={() => setMetricsPickerOpen(false)}
          eyebrow="STOCK METRICS"
          subtitle="Select which tiles to show for this stock"
          ariaLabel="Stock metrics"
          emptyText="No stock metrics available — is the backend running?"
        />
      )}

      {/* About — its own loading/error state, independent of the header
          above: a description is always a live call and can fail on its
          own without the name/sector that already loaded successfully. */}
      <section className="bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] p-5 flex flex-col gap-2">
        <div className="eyebrow">ABOUT</div>
        {descriptionLoading ? (
          <Loading variant="skeleton" lines={4} />
        ) : descriptionError ? (
          <p className="text-[13px] text-[var(--fg-2)] leading-relaxed m-0">
            Description unavailable right now.{' '}
            <button
              onClick={retryDescription}
              className="text-[var(--accent)] underline cursor-pointer bg-transparent border-none p-0 text-[13px]"
            >
              Retry
            </button>
          </p>
        ) : (
          <p className="text-[13.5px] text-[var(--fg-1)] leading-relaxed m-0">
            {descriptionData?.description || 'No description available for this company.'}
          </p>
        )}
      </section>
    </>
  );
});

/** The real price chart, its timeframe tabs and its candle toggle — its
 *  own component, not inline in StockDetail, so useLiveSeries only fires
 *  while this is actually mounted. Rendered only while nothing is being
 *  compared (issue #160): useLiveSeries has no "disabled" switch of its
 *  own (see the note at the top of this file), so the only way to stop it
 *  fetching and holding a series nobody is drawing once ComparisonChart
 *  takes this slot is to unmount the component that calls it — the same
 *  fix issue #158 already used for the empty-ticker case on this page. */
const PricePerformance = memo(function PricePerformance({ ticker, timeframe, onTimeframeChange }) {
  const { arr, dates, candles, loading: chartLoading } = useLiveSeries(ticker, timeframe);
  const pct = arr && arr.length > 1 ? ((arr[arr.length - 1] - arr[0]) / arr[0]) * 100 : 0;

  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <TimeframeTabs active={timeframe} onChange={onTimeframeChange} />
          {!chartLoading && arr && (
            <span
              className="font-[var(--font-mono)] text-[15px] font-bold tabular-nums"
              style={{ color: pct >= 0 ? 'var(--success)' : 'var(--danger)' }}
            >
              {(pct >= 0 ? '+' : '') + pct.toFixed(1) + '%'}
            </span>
          )}
        </div>
        <CandleToggle />
      </div>
      <div className="relative">
        {chartLoading || !arr ? (
          <Loading variant="chart" height={280} />
        ) : (
          <PriceChart
            arr={arr}
            dates={dates}
            candles={candles}
            pct={pct}
            timeframe={timeframe}
            gradientId="stockPageChart"
            height={280}
          />
        )}
      </div>
    </>
  );
});

/** The chart's timeframe, held in `?tf=` so a reload or a link reopens the
 *  same reading — the same reasoning the dashboard's own window lives in
 *  the URL for. Defaults to 1Y, the same default useLiveSeries itself uses. */
function useTimeframeParam() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tf = searchParams.get('tf');
  const timeframe = VALID_TIMEFRAMES.includes(tf) ? tf : '1Y';
  const setTimeframe = (next) => {
    const params = new URLSearchParams(searchParams);
    params.set('tf', next);
    setSearchParams(params, { replace: true });
  };
  return [timeframe, setTimeframe];
}
