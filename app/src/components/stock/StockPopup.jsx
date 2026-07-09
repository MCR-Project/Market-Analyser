/**
 * StockPopup — full-screen modal showing deep detail for a single stock.
 *
 * Layout (two-pane, 900px wide):
 *  ┌────────────────────────────────────────────────┐
 *  │ Header: logo, ticker, name, tags, weight, value│
 *  ├────────────────────────┬───────────────────────┤
 *  │ Left: Performance      │ Right: Correlation    │
 *  │  • 1W/1M/1Y/5Y tabs    │ Explorer              │
 *  │    with return %       │ • min ρ slider        │
 *  │  • AreaChart sparkline │ • combined ETF weight │
 *  │    with hover tooltip  │ • scrollable peer list│
 *  │                        │    with ρ bars + logos│
 *  └────────────────────────┴───────────────────────┘
 *
 * Clicking a peer card navigates to that stock (onNavigate).
 * All data (name/sector, price series, correlation, peer names) is
 * fetched live from the API. Each section renders <Loading> in place
 * of its content until its own request resolves — nothing here falls
 * back to fabricated/mock values.
 */
import { memo, useState, useMemo, useCallback, useEffect } from 'react';
import { fmtCorr, fmtMoney } from '../../utils/format';
import { useLiveSeries } from '../../hooks/useLiveSeries';
import { useChartHover } from '../../hooks/useChartHover';
import { useFetch } from '../../hooks/useFetch';
import { AreaChart } from '../charts/AreaChart';
import { ChartTooltip } from '../charts/ChartTooltip';
import { Logo } from '../ui/Logo';
import { Loading } from '../ui/Loading';
import { api } from '../../utils/api';

const TF_LIST = ['1W', '1M', '1Y', '5Y'];
const PERIOD_MAP = { '1W': '5d', '1M': '1mo', '1Y': '1y', '5Y': '5y' };

export const StockPopup = memo(function StockPopup({ ticker, etf, tickers, weightOf, onClose, onNavigate, corrMatrix, corrLoading, corrIsLive, etfLoading, etfIsLive }) {
  const [chartTf, setChartTf] = useState('1Y');
  const [rhoMin, setRhoMin] = useState(0.5);

  // Stock identity (name, sector, exchange) — live from the API
  const { data: stockInfo, loading: stockLoading } = useFetch(
    () => api.getStock(ticker),
    [ticker],
    { fallback: null }
  );

  const weight = weightOf(ticker);

  // Chart data for the selected timeframe
  const { arr, dates, loading: chartLoading } = useLiveSeries(ticker, chartTf);
  const pct = arr && arr.length > 1 ? ((arr[arr.length - 1] - arr[0]) / arr[0]) * 100 : 0;
  const positive = pct >= 0;
  const { hoverIdx, onMouseMove, onMouseLeave, tooltip } = useChartHover(arr, chartTf, dates);

  const corrFn = useCallback((a, b) => corrMatrix?.[a]?.[b] ?? null, [corrMatrix]);

  // Batch-fetch names for every holding, used to label peer cards
  const { data: peerInfos, loading: peerNamesLoading } = useFetch(
    () => api.getStocks(tickers),
    [tickers.join(',')],
    { fallback: [] }
  );
  const peerNameMap = useMemo(
    () => Object.fromEntries((peerInfos || []).map(s => [s.ticker, s.name])),
    [peerInfos]
  );

  // Fetch return % for each timeframe independently
  const [perfReturns, setPerfReturns] = useState({});
  useEffect(() => {
    setPerfReturns({});
    const controllers = [];
    for (const tf of TF_LIST) {
      const ctrl = new AbortController();
      controllers.push(ctrl);
      api.getSeries(ticker, PERIOD_MAP[tf])
        .then(data => {
          if (!ctrl.signal.aborted && data?.length > 1) {
            const first = data[0].close;
            const last = data[data.length - 1].close;
            const ret = ((last - first) / first) * 100;
            setPerfReturns(prev => ({ ...prev, [tf]: ret }));
          }
        })
        .catch(() => {});
    }
    return () => controllers.forEach(c => c.abort());
  }, [ticker]);

  const perfs = TF_LIST.map(tf => {
    const ret = perfReturns[tf] ?? (tf === chartTf && arr ? pct : null);
    return { tf, ret, pos: ret !== null ? ret >= 0 : true, loading: ret === null };
  });

  // Peer correlation list — only computed once the live matrix has resolved
  const peers = useMemo(() => {
    if (!corrIsLive) return [];
    return tickers
      .filter(t => t !== ticker)
      .map(t => ({ ticker: t, rho: corrFn(ticker, t), w: weightOf(t) }))
      .filter(p => p.rho !== null && p.rho >= rhoMin)
      .sort((a, b) => b.rho - a.rho);
  }, [ticker, tickers, rhoMin, weightOf, corrFn, corrIsLive]);

  const peerTotalW = (peers.reduce((s, p) => s + p.w, 0) + weight).toFixed(1) + '%';
  const maxRho = peers.length ? peers[0].rho : 1;

  return (
    <div onClick={onClose} className="fixed inset-0 z-[150] flex items-center justify-center p-6" style={{ background: 'rgba(0,0,0,0.45)' }}>
      <div onClick={e => e.stopPropagation()} className="w-[900px] max-h-[86vh] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] animate-[spPop_220ms_var(--ease-out)] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between p-[24px_28px_20px] border-b border-[var(--divider)] gap-5 flex-none">
          <div className="flex items-center gap-4 min-w-0">
            <Logo ticker={ticker} name={stockInfo?.name} size={52} />
            <div className="flex flex-col gap-2 min-w-0">
              <div className="flex items-baseline gap-3.5 flex-wrap">
                <span className="font-[var(--font-mono)] text-[30px] font-extrabold text-[var(--accent)] tracking-tight leading-none">{ticker}</span>
                {stockLoading ? (
                  <Loading variant="skeleton" lines={1} className="w-40" />
                ) : (
                  <span className="text-[19px] font-semibold text-[var(--fg)] tracking-tight">{stockInfo?.name || ticker}</span>
                )}
                <span className="text-xs font-[var(--font-mono)] text-[var(--fg-2)]">{etf.id}</span>
              </div>
              <div className="flex items-center gap-[7px] flex-wrap">
                {stockLoading ? (
                  <Loading variant="skeleton" lines={1} className="w-28" />
                ) : (
                  <>
                    <span className="text-xs text-[var(--fg-2)] bg-[var(--bg-3)] rounded-full py-[3px] px-2.5">{stockInfo?.sector || 'Unknown'}</span>
                    {stockInfo?.sectorTag && (
                      <span className="text-[11px] text-[var(--fg-3)] bg-[var(--bg-3)] rounded-full py-0.5 px-2.5 font-[var(--font-mono)]">{stockInfo.sectorTag}</span>
                    )}
                    {stockInfo?.exchange && (
                      <span className="text-[11px] text-[var(--fg-3)] bg-[var(--bg-3)] rounded-full py-0.5 px-2.5 font-[var(--font-mono)]">{stockInfo.exchange}</span>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-5 flex-none">
            <div className="flex gap-6">
              <div className="text-right">
                <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-[3px]">IN {etf.id}</div>
                {etfLoading ? (
                  <RightLoading width={44} />
                ) : (
                  <div className="text-[22px] font-extrabold tabular-nums tracking-tight" style={{ color: etfIsLive ? 'var(--fg)' : 'var(--fg-3)' }}>
                    {etfIsLive ? weight.toFixed(1) + '%' : '—'}
                  </div>
                )}
              </div>
              <div className="text-right">
                <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-[3px]">MARKET VALUE</div>
                {etfLoading ? (
                  <RightLoading width={60} />
                ) : (
                  <div className="text-[22px] font-extrabold tabular-nums tracking-tight" style={{ color: etfIsLive ? 'var(--fg)' : 'var(--fg-3)' }}>
                    {etfIsLive ? fmtMoney(etf.aum * weight / 100) : '—'}
                  </div>
                )}
              </div>
            </div>
            <button onClick={onClose} className="w-[34px] h-[34px] rounded-full border border-[var(--border)] bg-[var(--bg-3)] cursor-pointer grid place-items-center text-[var(--fg-2)] flex-none transition-colors duration-150">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="m18 6-12 12M6 6l12 12" /></svg>
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex h-[560px] overflow-hidden">
          {/* LEFT: performance */}
          <div className="flex-1 min-w-0 p-[22px_28px] overflow-y-auto flex flex-col gap-4 border-r border-[var(--divider)]">
            <div className="eyebrow">PERFORMANCE</div>
            <div className="grid grid-cols-4 gap-2.5">
              {perfs.map(p => (
                <button key={p.tf} onClick={() => setChartTf(p.tf)}
                  className="p-[10px_14px] border-none rounded-lg cursor-pointer w-full text-left transition-all duration-150"
                  style={{ background: chartTf === p.tf ? 'var(--bg-3)' : 'transparent', boxShadow: chartTf === p.tf ? 'var(--shadow-xs)' : 'none' }}
                >
                  <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] mb-[5px]">{p.tf}</div>
                  <div className="font-[var(--font-mono)] text-[17px] font-extrabold tabular-nums tracking-tight" style={{ color: p.loading ? 'var(--fg-3)' : (p.pos ? 'var(--success)' : 'var(--danger)') }}>
                    {p.loading ? '…' : (p.pos ? '+' : '') + p.ret.toFixed(1) + '%'}
                  </div>
                </button>
              ))}
            </div>
            <div className="relative mt-20">
              {chartLoading || !arr
                ? <Loading variant="chart" height={180} />
                : <>
                    <AreaChart data={arr} pct={pct} hoverIdx={hoverIdx} onMouseMove={onMouseMove} onMouseLeave={onMouseLeave} gradientId="spChart" height={180} />
                    <ChartTooltip tooltip={tooltip} />
                  </>
              }
            </div>
          </div>

          {/* RIGHT: correlation explorer */}
          <div className="w-[310px] flex-none flex flex-col bg-[var(--bg)] overflow-hidden">
            <div className="flex-none p-[22px_22px_14px] flex flex-col gap-3 border-b border-[var(--divider)]">
              <div className="eyebrow">CORRELATION EXPLORER</div>
              <div className="flex items-center gap-2.5">
                <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)] flex-none">min ρ</span>
                <input type="range" className="corr-range flex-1" min={0.10} max={0.99} step={0.01} value={rhoMin} onInput={e => setRhoMin(parseFloat(e.target.value))} />
                <span className="font-[var(--font-mono)] text-[13px] font-bold text-[var(--fg)] w-[34px] text-right tabular-nums">{rhoMin.toFixed(2)}</span>
              </div>
              <div className="flex items-center justify-between p-[10px_13px] bg-[var(--accent-soft)] rounded-[var(--radius-md)]">
                <div>
                  <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-0.5">COMBINED ETF WEIGHT</div>
                  <div className="text-xs text-[var(--fg-2)]">{ticker} + correlated</div>
                </div>
                {corrLoading || etfLoading ? (
                  <RightLoading width={56} />
                ) : !corrIsLive || !etfIsLive ? (
                  <span className="font-[var(--font-mono)] text-xl font-extrabold text-[var(--fg-3)] tracking-tight">—</span>
                ) : (
                  <span className="font-[var(--font-mono)] text-xl font-extrabold text-[var(--accent)] tracking-tight">{peerTotalW}</span>
                )}
              </div>
            </div>

            <div className="corr-scroll flex-1 overflow-y-auto p-[12px_22px_22px] flex flex-col gap-2">
              {corrLoading ? (
                Array.from({ length: 5 }, (_, i) => <Loading key={i} variant="skeleton" lines={1} />)
              ) : !corrIsLive ? (
                <div className="text-center py-10 text-[13px] text-[var(--fg-3)] leading-relaxed">
                  Correlation data unavailable<br /><span className="text-[11px]">Try again later</span>
                </div>
              ) : peers.length === 0 ? (
                <div className="text-center py-10 text-[13px] text-[var(--fg-3)] leading-relaxed">
                  No stocks correlated at<br />ρ ≥ {rhoMin.toFixed(2)}<br /><span className="text-[11px]">Try lowering the threshold</span>
                </div>
              ) : (
                peers.map(pr => (
                  <button key={pr.ticker} onClick={() => onNavigate(pr.ticker)}
                    className="flex flex-col gap-1.5 w-full bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-md)] p-[9px_12px] cursor-pointer text-left flex-none transition-all duration-150"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0 overflow-hidden flex items-center gap-1.5">
                        <Logo ticker={pr.ticker} name={peerNameMap[pr.ticker]} size={20} />
                        <span className="font-[var(--font-mono)] text-[13px] font-bold text-[var(--accent)]">{pr.ticker}</span>
                        <div className="text-xs text-[var(--fg-2)] ml-0.5 whitespace-nowrap overflow-hidden text-ellipsis">
                          {peerNameMap[pr.ticker] || (peerNamesLoading ? <Loading variant="skeleton" lines={1} className="w-16" /> : pr.ticker)}
                        </div>
                      </div>
                      <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-3)] flex-none">
                        {etfLoading ? '…' : etfIsLive ? pr.w.toFixed(1) + '%' : '—'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] flex-none">ρ</span>
                      <div className="flex-1 h-[5px] rounded-full bg-[var(--bg-3)] overflow-hidden"><div className="h-full bg-[var(--accent)] rounded-full" style={{ width: Math.round((pr.rho / maxRho) * 100) + '%' }} /></div>
                      <span className="font-[var(--font-mono)] text-xs font-bold text-[var(--accent)] w-8 text-right tabular-nums">{fmtCorr(pr.rho)}</span>
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});


/** Right-aligned shimmer placeholder for a single stat value (header, badges). */
function RightLoading({ width }) {
  return (
    <div className="flex justify-end">
      <Loading variant="skeleton" lines={1} style={{ width }} />
    </div>
  );
}
