/**
 * DetailAside — right sidebar shown alongside Matrix and Network views.
 *
 * Two states:
 *  A. No selection → "Pair Insights" panel:
 *     • Strongest / loosest / most-connected pair stats
 *     • Sector mix breakdown with count bars
 *
 *  B. Stock selected → stock detail:
 *     • Ticker, name, sector
 *     • Value and weight stat cards
 *     • Ranked peer correlation list (clickable to switch selection)
 *
 * Height (issue #176): the panel is exactly as tall as the plot beside it —
 * `self-stretch` in the views' row; where the row wraps and it sits below
 * the plot it is MIN_H, as the plot's own section is at least — and never
 * under MIN_H, so the list
 * inside it always has room to scroll. Its content is laid out in an
 * absolutely positioned box, so how many peers there are cannot make the
 * panel, and through it the matrix or graph, any taller: the list scrolls
 * instead. It used to be as tall as its content but capped at the view's
 * visible height, which on a short window left the list a few pixels high.
 * (`min-h-[480px]` below is MIN_H: about 260px of fixed header and tiles,
 * and 200px or so of list.)
 */
import { memo, useMemo, useCallback } from 'react';
import { useLiveStocks } from '../hooks/useLiveStocks';
import { fmtCorr, fmtMoney } from '../utils/format';
import { pairInsights } from '../utils/pairInsights';

export const DetailAside = memo(function DetailAside({ etf, tickers, selected, onSelect, correlationData, sectorData }) {
  const { stockMap } = useLiveStocks(tickers);

  const selData = useMemo(() => {
    if (!selected || !tickers.includes(selected)) return null;
    const s = stockMap[selected] || { name: selected, sector: 'Unknown' };
    const w = etf.holdings.find(x => x[0] === selected)?.[1] || 0;
    return { ticker: selected, name: s.name, sector: s.sector, weight: w.toFixed(1), value: fmtMoney(etf.aum * w / 100) };
  }, [selected, tickers, etf, stockMap]);

  const corrMatrix = correlationData?.matrix;
  // No mock fallback — a peer missing from the live matrix (e.g. a ticker
  // dropped by the backend for insufficient price history) resolves to
  // null and is filtered out below rather than shown with a fake ρ.
  const corrFn = useCallback((a, b) => corrMatrix?.[a]?.[b] ?? null, [corrMatrix]);

  // The backend's strongest/loosest/hub cover its whole matrix, which for a
  // deep-filled fund includes Untracked holdings this view does not draw
  // (issue #172) - so they are recomputed over the tickers shown. A fund that is
  // not deep-filled keeps the backend's own figures, which are the same thing.
  const insights = useMemo(() => (
    correlationData?.deepFill
      ? pairInsights(corrMatrix, tickers)
      : { strongest: correlationData?.strongest, weakest: correlationData?.weakest, hub: correlationData?.hub }
  ), [correlationData, corrMatrix, tickers]);

  const peers = useMemo(() => {
    if (!selData) return [];
    return tickers
      .filter(t => t !== selected)
      .map(t => ({ ticker: t, val: corrFn(selected, t) }))
      .filter(p => p.val != null)
      .sort((a, b) => b.val - a.val);
  }, [selData, selected, tickers, corrFn]);

  // Math.max(...[]) is -Infinity — guard with a floor of 1 so an ETF with
  // no sector data (empty sectorCounts) can't poison the width% below.
  const maxSecCount = useMemo(() => Math.max(1, ...Object.values(sectorData.sectorCounts)), [sectorData]);

  return (
    <aside className="relative w-[320px] flex-none self-stretch min-h-[480px] overflow-hidden bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)]">
      <div className="absolute inset-0 flex flex-col p-[18px]">
        {selData ? (
          <>
            <div className="flex-none flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-[var(--font-mono)] text-[13px] font-bold text-[var(--accent)]">{selData.ticker}</div>
                <div className="text-lg font-bold text-[var(--fg)] tracking-tight mt-0.5">{selData.name}</div>
                <div className="text-[13px] text-[var(--fg-2)] mt-0.5">{selData.sector}</div>
              </div>
              <button onClick={() => onSelect(null)} aria-label="Clear" className="flex-none w-7 h-7 grid place-items-center bg-transparent border border-[var(--border)] rounded-[var(--radius-sm)] text-[var(--fg-2)] cursor-pointer">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            </div>

            <div className="flex-none flex gap-2.5 mt-4 mb-1">
              <div className="flex-1 bg-[var(--bg-3)] rounded-[var(--radius-sm)] p-[10px_12px]">
                <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-[3px]">VALUE</div>
                <div className="text-lg font-bold text-[var(--fg)] tabular-nums">{selData.value}</div>
              </div>
              <div className="flex-1 bg-[var(--bg-3)] rounded-[var(--radius-sm)] p-[10px_12px]">
                <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-[3px]">WEIGHT</div>
                <div className="text-lg font-bold text-[var(--fg)] tabular-nums">{selData.weight}%</div>
              </div>
            </div>

            <div className="flex-none font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] mt-4 mb-2.5">CORRELATION TO PEERS</div>
            <div className="corr-scroll flex-1 min-h-0 overflow-y-auto flex flex-col gap-2 pr-1 -mr-1">
              {peers.map(p => (
                <button key={p.ticker} onClick={() => onSelect(p.ticker)} className="flex-none flex items-center gap-2.5 bg-transparent border-none p-0 cursor-pointer text-left">
                  <span className="w-[52px] flex-none font-[var(--font-mono)] text-xs text-[var(--fg-1)]">{p.ticker}</span>
                  <span className="flex-1 h-2 rounded-full bg-[var(--bg-3)] overflow-hidden"><span className="block h-full rounded-full" style={{ width: Math.round(Math.abs(p.val) * 100) + '%', background: p.val < 0 ? 'var(--negative)' : 'var(--accent)' }} /></span>
                  <span className="w-8 flex-none text-right text-xs tabular-nums text-[var(--fg)]">{fmtCorr(p.val)}</span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="corr-scroll flex-1 min-h-0 overflow-y-auto flex flex-col">
            <div className="font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] mb-3.5">PAIR INSIGHTS</div>
            <p className="text-sm text-[var(--fg-1)] leading-relaxed m-0 mb-4">
              Daily-return correlation across <strong className="text-[var(--fg)]">{etf.id}</strong> holdings — how tightly they move together, beyond their sector labels.
            </p>

            {insights.strongest && insights.weakest && insights.hub ? (
              <div className="flex flex-col gap-3">
                <InsightRow label="Strongest pair" pair={insights.strongest} color="var(--accent)" />
                <InsightRow label="Loosest pair" pair={insights.weakest} color="var(--fg-2)" />
                <div className="flex items-center justify-between p-3 bg-[var(--bg-3)] rounded-[var(--radius-md)]">
                  <span className="text-[13px] text-[var(--fg-2)]">Most connected</span>
                  <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg)]">
                    {insights.hub.ticker}{' '}
                    <span className="text-[var(--accent)] font-bold">{fmtCorr(insights.hub.avgCorr)}</span>
                  </span>
                </div>
              </div>
            ) : (
              <div className="text-sm text-[var(--fg-3)] py-4 text-center">Correlation data unavailable</div>
            )}

            <div className="font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] mt-5 mb-2.5">SECTOR MIX</div>
            <div className="flex flex-col gap-2">
              {Object.entries(sectorData.sectorCounts).sort((a, b) => b[1] - a[1]).map(([name, count]) => (
                <div key={name} className="flex items-center gap-2.5">
                  <span className="flex-1 text-[13px] text-[var(--fg-1)]">{name}</span>
                  <span className="w-[90px] flex-none h-1.5 rounded-full bg-[var(--bg-3)] overflow-hidden"><span className="block h-full bg-[var(--accent)] rounded-full" style={{ width: Math.round((count / maxSecCount) * 100) + '%' }} /></span>
                  <span className="w-[26px] flex-none text-right text-xs text-[var(--fg-2)] tabular-nums">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
});

function InsightRow({ label, pair, color }) {
  return (
    <div className="flex items-center justify-between p-3 bg-[var(--bg-3)] rounded-[var(--radius-md)]">
      <span className="text-[13px] text-[var(--fg-2)]">{label}</span>
      <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg)]">
        {pair.a} ↔ {pair.b}{' '}
        <span style={{ color }} className="font-bold">{fmtCorr(pair.value)}</span>
      </span>
    </div>
  );
}
