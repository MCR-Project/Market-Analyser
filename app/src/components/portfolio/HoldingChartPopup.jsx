/**
 * HoldingChartPopup — a Holding's own price chart, opened from its ticker
 * in HoldingsTable.
 *
 * Deliberately not StockPopup reused: StockPopup's right-hand pane needs an
 * ETF's correlation matrix and full constituent list, neither of which a
 * portfolio Holding has (it may not belong to any ETF at all — issue #137).
 * This is the same timeframe-tabs + AreaChart pattern as StockPopup's own
 * left pane, kept in its own component rather than sharing one, so this
 * component never has to fake ETF context and StockPopup is never at risk
 * of a regression from a change made here.
 *
 * weight/value are the Holding's own applied figures from the current Run —
 * the same numbers HoldingsTable's own WEIGHT/VALUE columns show, dimmed
 * under the same `stale` condition, so the header reads as "this row,
 * expanded" rather than a second source of truth.
 */
import { memo, useState } from 'react';
import { useLiveSeries } from '../../hooks/useLiveSeries';
import { useChartHover } from '../../hooks/useChartHover';
import { useFetch } from '../../hooks/useFetch';
import { AreaChart } from '../charts/AreaChart';
import { ChartTooltip } from '../charts/ChartTooltip';
import { Logo } from '../ui/Logo';
import { Loading } from '../ui/Loading';
import { Overlay } from '../ui/Overlay';
import { api } from '../../utils/api';
import { fmtUSD0 } from '../../utils/format';

const TF_LIST = ['1W', '1M', '1Y', '5Y'];

export const HoldingChartPopup = memo(function HoldingChartPopup({ ticker, weight, value, stale, onClose }) {
  const [chartTf, setChartTf] = useState('1Y');

  const { data: stockInfo, loading: stockLoading } = useFetch(
    (signal) => api.getStock(ticker, { signal }),
    [ticker],
    { fallback: null }
  );

  const { arr, dates, loading: chartLoading } = useLiveSeries(ticker, chartTf);
  const pct = arr && arr.length > 1 ? ((arr[arr.length - 1] - arr[0]) / arr[0]) * 100 : 0;
  const { hoverIdx, onMouseMove, onMouseLeave, tooltip } = useChartHover(arr, chartTf, dates);

  return (
    <Overlay
      onClose={onClose}
      labelledBy="holding-chart-title"
      className="fixed inset-0 z-[150] flex items-center justify-center p-6"
      style={{ background: 'var(--bg-inset)' }}
      contentClassName="w-[520px] max-h-[86vh] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] animate-[spPop_220ms_var(--ease-out)] flex flex-col overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-start justify-between p-[24px_28px_20px] border-b border-[var(--divider)] gap-5 flex-none">
        <div className="flex items-center gap-4 min-w-0">
          <Logo ticker={ticker} name={stockInfo?.name} size={44} />
          <div className="flex flex-col gap-2 min-w-0">
            <span id="holding-chart-title" className="contents">
              <span className="font-[var(--font-mono)] text-[24px] font-extrabold text-[var(--accent)] tracking-tight leading-none">{ticker}</span>
              {stockLoading ? (
                <Loading variant="skeleton" lines={1} className="w-40" />
              ) : (
                <span className="text-[15px] font-semibold text-[var(--fg)] tracking-tight">{stockInfo?.name || ticker}</span>
              )}
            </span>
            {!stockLoading && stockInfo?.sector && (
              <span className="text-xs text-[var(--fg-2)] bg-[var(--bg-3)] rounded-full py-[3px] px-2.5 w-fit">{stockInfo.sector}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-5 flex-none">
          <div className="flex gap-5">
            <div className="text-right">
              <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-[3px]">WEIGHT</div>
              <div className="text-[18px] font-extrabold tabular-nums tracking-tight text-[var(--fg)]" style={{ opacity: stale ? 0.5 : 1 }}>
                {weight}%
              </div>
            </div>
            <div className="text-right">
              <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-[3px]">VALUE</div>
              <div className="text-[18px] font-extrabold tabular-nums tracking-tight text-[var(--fg)]" style={{ opacity: stale ? 0.5 : 1 }}>
                {value !== null && value !== undefined ? fmtUSD0(value) : '—'}
              </div>
            </div>
          </div>
          <button onClick={onClose} className="w-[34px] h-[34px] rounded-full border border-[var(--border)] bg-[var(--bg-3)] cursor-pointer grid place-items-center text-[var(--fg-2)] flex-none transition-colors duration-150">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="m18 6-12 12M6 6l12 12" /></svg>
          </button>
        </div>
      </div>

      {/* Chart */}
      <div className="p-[22px_28px] flex flex-col gap-4">
        <div className="grid grid-cols-4 gap-2">
          {TF_LIST.map(tf => (
            <button key={tf} onClick={() => setChartTf(tf)}
              className="py-1.5 border-none rounded-lg cursor-pointer w-full text-center font-[var(--font-mono)] text-[12px] font-semibold transition-all duration-150"
              style={{
                background: chartTf === tf ? 'var(--bg-3)' : 'transparent',
                color: chartTf === tf ? 'var(--fg)' : 'var(--fg-2)',
                boxShadow: chartTf === tf ? 'var(--shadow-xs)' : 'none',
              }}
            >
              {tf}
            </button>
          ))}
        </div>
        <div className="relative mt-4">
          {chartLoading || !arr
            ? <Loading variant="chart" height={180} />
            : <>
                <AreaChart data={arr} pct={pct} hoverIdx={hoverIdx} onMouseMove={onMouseMove} onMouseLeave={onMouseLeave} gradientId="holdingChart" height={180} />
                <ChartTooltip tooltip={tooltip} />
              </>
          }
        </div>
      </div>
    </Overlay>
  );
});
