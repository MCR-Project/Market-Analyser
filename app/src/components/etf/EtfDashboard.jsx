/**
 * EtfDashboard — persistent top card showing the active ETF at a glance.
 *
 * Fully self-contained: owns the active-ETF selection (via useLiveEtf,
 * backed by the shared useEtfStore), fetches its own correlation
 * averages and sector breakdown, and manages its own ETF-picker modal.
 * Nothing here is drilled down from a parent — any other component that
 * needs the active ETF calls useLiveEtf() itself and reads the same
 * shared etfId, so switching ETFs from this card stays in sync
 * everywhere else in the app automatically.
 *
 * Three zones laid out horizontally (wraps on narrow screens):
 *  ┌──────────────────┬───────────┬─────────────────┐
 *  │ Zone 1+2:        │ Zone 3:   │ Zone 4:         │
 *  │ Identity button  │ Sector    │ Market value    │
 *  │ (ticker, name,   │ zone with │ chart with      │
 *  │  description,    │ hover     │ timeframe tabs  │
 *  │  AUM/holdings/ρ) │ ranking   │ and sparkline   │
 *  └──────────────────┴───────────┴─────────────────┘
 */
import { memo, useState, useMemo } from 'react';
import { fmtMoney, fmtCorr } from '../../utils/format';
import { useLiveEtf } from '../../hooks/useLiveEtf';
import { useLiveCorrelation } from '../../hooks/useLiveCorrelation';
import { useLiveSectors } from '../../hooks/useLiveSectors';
import { useLiveSeries } from '../../hooks/useLiveSeries';
import { useChartHover } from '../../hooks/useChartHover';
import { AreaChart } from '../charts/AreaChart';
import { ChartTooltip } from '../charts/ChartTooltip';
import { TimeframeTabs } from '../ui/TimeframeTabs';
import { SectorZone } from './SectorZone';
import { Loading } from '../ui/Loading';
import { ErrorState } from '../ui/ErrorState';
import { EtfPicker } from './EtfPicker';

export const EtfDashboard = memo(function EtfDashboard() {
  const [timeframe, setTimeframe] = useState('1Y');
  const [pickerOpen, setPickerOpen] = useState(false);

  const { etf, etfId, tickers, allEtfs, switchEtf, loading: etfLoading, retry: etfRetry, forceRefresh } = useLiveEtf();

  // "Danger mode" — the backend served a live yfinance fallback (top-~10)
  // instead of the full DB-backed holdings list, e.g. right after a DB
  // miss before the short fallback TTL expires. See is_etf_holdings_stale
  // in services/market_data.py.
  const stale = !!etf?.stale;

  // threshold=0 — this card only needs the per-ticker averages, not the
  // edge count used elsewhere by the network view's threshold slider.
  const corrData = useLiveCorrelation(etfId, tickers, 0);
  const sectors = useLiveSectors(etfId);

  const avgCorr = useMemo(() => {
    const vals = Object.values(corrData.averages || {});
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  }, [corrData.averages]);

  const { arr, dates, loading } = useLiveSeries(etfId, timeframe);
  const pct = arr && arr.length > 1 ? ((arr[arr.length - 1] - arr[0]) / arr[0]) * 100 : 0;
  const positive = pct >= 0;

  const { hoverIdx, onMouseMove, onMouseLeave, tooltip } = useChartHover(arr, timeframe, dates);

  const handlePickerSelect = (id) => {
    switchEtf(id);
    setPickerOpen(false);
  };

  // This component fetches its own copy of the ETF (see useLiveEtf), so
  // it can render before/without data even when a parent's copy resolved.
  if (!etf) {
    return etfLoading ? (
      <section className="flex-none bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] p-6 mb-5">
        <Loading variant="skeleton" lines={5} />
      </section>
    ) : (
      <ErrorState onRetry={etfRetry} className="flex-none mb-5" />
    );
  }

  return (
    <>
      <section className="flex-none flex gap-0 items-stretch flex-wrap bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] overflow-hidden mb-5 animate-[corrFadeUp_var(--dur-base)_var(--ease-out)]">
        {/* Identity + Description */}
        <div className="flex-[1.5] min-w-[280px] flex flex-col p-5 gap-3.5 border-r border-[var(--divider)]" style={{ padding: '20px 22px' }}>
          <div className="flex items-stretch gap-2">
            <button
              onClick={() => setPickerOpen(true)}
              className="flex-1 min-w-0 flex items-center gap-3.5 bg-transparent border border-[var(--border)] rounded-[var(--radius-md)] p-3 cursor-pointer text-left transition-colors duration-150 hover:bg-[var(--bg-2)] hover:border-[var(--border-strong)]"
            >
              <div className="min-w-0 flex-1">
                <div className="eyebrow mb-[7px]">● ACTIVE ETF</div>
                <div className="flex items-baseline gap-2.5 flex-wrap">
                  <span className="text-[26px] font-extrabold text-[var(--fg)] tracking-tight leading-none">{etf.id}</span>
                  <span className="text-sm text-[var(--fg-2)] min-w-0">{etf.name}</span>
                </div>
              </div>
              <span className="flex-none flex items-center gap-1.5 font-[var(--font-mono)] text-[11px] text-[var(--accent)] border border-[var(--accent-ring)] rounded-full px-2.5 py-1">
                Change
              </span>
            </button>
          </div>

          <div className="flex-1">
            <div className="eyebrow mb-2">DESCRIPTION</div>
            <p className="text-sm leading-relaxed text-[var(--fg-1)] m-0">{etf.desc}</p>
          </div>

          <div className="flex justify-between items-center">
            <div className="relative group/stats flex gap-6 flex-wrap pt-3 border-t border-[var(--divider)]">
              <Stat label="NET ASSETS" value={fmtMoney(etf.aum)} danger={stale} />
              <Stat label="HOLDINGS" value={tickers.length} danger={stale} />
              <Stat label="AVG ρ" value={corrData.loading ? <Loading variant="skeleton" lines={1} style={{ width: 32 }} /> : fmtCorr(avgCorr)} danger={stale} />

              {stale && (
                <div className="pointer-events-none absolute left-0 bottom-full mb-2.5 w-64 opacity-0 -translate-y-1 group-hover/stats:opacity-100 group-hover/stats:translate-y-0 transition-all duration-150 z-20">
                  <div className="relative bg-[var(--bg-3)] border border-[var(--warning-ring)] text-[var(--fg-1)] text-xs leading-relaxed rounded-[var(--radius-md)] shadow-[var(--shadow-md)] px-3 py-2.5">
                    <span className="font-semibold text-[var(--warning)]">Data may be incomplete —</span> these figures came from a live fallback, not the database. Hit refresh to try loading the full data again.
                    <div className="absolute left-4 top-full w-2.5 h-2.5 -mt-1.5 bg-[var(--bg-3)] border-r border-b border-[var(--warning-ring)] rotate-45" />
                  </div>
                </div>
              )}
            </div>

            <button
              onClick={forceRefresh}
              disabled={etfLoading}
              title="Refresh — bypass cache and re-fetch now"
              aria-label="Refresh ETF data"
              className="flex-none w-11 h-11 grid place-items-center bg-transparent border border-[var(--border)] rounded-[var(--radius-md)] cursor-pointer text-[var(--fg-2)] transition-colors duration-150 hover:bg-[var(--bg-2)] hover:border-[var(--border-strong)] hover:text-[var(--fg)] disabled:opacity-50 disabled:cursor-wait"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={etfLoading ? 'animate-spin' : ''}>
                <path d="M21 12a9 9 0 1 1-2.64-6.36" />
                <path d="M21 3v6h-6" />
              </svg>
            </button>
          </div>
        </div>

        {/* Sector zone */}
        {sectors.loading || !sectors.topSector ? (
          <div className="flex-none w-[168px] flex flex-col justify-center p-5 gap-2.5 border-r border-[var(--divider)]">
            <Loading variant="skeleton" lines={4} />
          </div>
        ) : (
          <SectorZone
            label={sectors.sectorLabel}
            tag={sectors.topSector.tag}
            name={sectors.topSector.name}
            share={sectors.topSector.share}
            ranking={sectors.ranking}
          />
        )}

        {/* Market chart */}
        <div className="flex-[1.2] min-w-[280px] flex flex-col" style={{ padding: '20px 22px' }}>
          <div className="flex items-start justify-between gap-3 mb-1.5">
            <div>
              <div className="eyebrow mb-[7px]">MARKET VALUE</div>
              <div className="flex items-baseline gap-2">
                <span className="text-[22px] font-extrabold text-[var(--fg)] tracking-tight tabular-nums">{fmtMoney(etf.aum)}</span>
                {loading || !arr
                  ? <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg-3)]">—</span>
                  : <span className="font-[var(--font-mono)] text-[13px] font-bold tabular-nums" style={{ color: positive ? 'var(--success)' : 'var(--danger)' }}>
                      {(positive ? '+' : '') + pct.toFixed(1) + '%'}
                    </span>
                }
              </div>
            </div>
            <TimeframeTabs active={timeframe} onChange={setTimeframe} />
          </div>
          <div className="flex-1 min-h-[140px] flex items-end relative">
            {loading || !arr
              ? <Loading variant="chart" height={140} className="self-stretch" />
              : <>
                  <AreaChart data={arr} pct={pct} hoverIdx={hoverIdx} onMouseMove={onMouseMove} onMouseLeave={onMouseLeave} gradientId="mainChart" height={140} />
                  <ChartTooltip tooltip={tooltip} />
                </>
            }
          </div>
        </div>
      </section>

      {pickerOpen && (
        <EtfPicker currentId={etfId} allEtfs={allEtfs} onSelect={handlePickerSelect} onClose={() => setPickerOpen(false)} />
      )}
    </>
  );
});

function Stat({ label, value, danger }) {
  return (
    <div>
      <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-[3px]">{label}</div>
      <div className={`text-base font-bold tabular-nums ${danger ? 'text-[var(--warning)]' : 'text-[var(--fg)]'}`}>{value}</div>
    </div>
  );
}
