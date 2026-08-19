/**
 * NetworkView — force-directed graph tab.
 *
 * Fully self-contained: fetches the active ETF's holdings/tickers and
 * correlation matrix itself, and owns its own "edge ρ ≥" threshold
 * toolbar and DetailAside panel. Only `selected`/`onSelect` are passed
 * in from the parent, since the highlighted stock is shared with
 * MatrixView and must survive switching between the two tabs.
 *
 * Nodes are sized by ETF weight (exponentially — see nodeRadius) and
 * filled with brand icons resolved by company name (utils/logo.js) via
 * SVG <pattern>. Edges connect stocks whose correlation ≥ threshold,
 * with line width proportional to ρ strength.
 *
 * Clicking a node selects it: dims unconnected nodes, brightens edges
 * to neighbors, and updates DetailAside with peer correlations.
 * Clicking the background deselects.
 *
 * Layout is computed once per ETF via a 400-iteration force simulation
 * (cached in utils/layout.js).
 */
import { memo, useState, useMemo, useCallback } from 'react';
import { useLiveEtf } from '../hooks/useLiveEtf';
import { useLiveCorrelation } from '../hooks/useLiveCorrelation';
import { useLiveSectors } from '../hooks/useLiveSectors';
import { useLiveStocks } from '../hooks/useLiveStocks';
import { computeLayout } from '../utils/layout';
import { fmtCorr } from '../utils/format';
import { logoUrl, fallbackFaviconUrl, handleSvgImageLogoError } from '../utils/logo';
import { DetailAside } from './DetailAside';
import { Loading } from '../components/ui/Loading';
import { ErrorState } from '../components/ui/ErrorState';

const W = 620, H = 440;

// Node radius bounds and reference weight (weightPct at/above which a
// node hits MAX_R). The curve is a genuine exponential (not sqrt/linear),
// so a 7% holding renders dramatically bigger than a 2% one — not just
// proportionally bigger — matching how a heavier position actually
// dominates the fund far more than its weight ratio alone suggests.
const MIN_R = 10, MAX_R = 60, REF_WEIGHT = 10, GROWTH = 4;

function nodeRadius(weightPct) {
  const t = Math.min(1, Math.max(0, weightPct) / REF_WEIGHT);
  const curve = (Math.exp(GROWTH * t) - 1) / (Math.exp(GROWTH) - 1);
  return MIN_R + curve * (MAX_R - MIN_R);
}

export const NetworkView = memo(function NetworkView({ selected, onSelect }) {
  const { etf, etfId, tickers, weightOf, loading: etfLoading, retry: etfRetry } = useLiveEtf();
  const [threshold, setThreshold] = useState(0.5);
  const corrData = useLiveCorrelation(etfId);
  const sectors = useLiveSectors(etfId);
  const { stockMap } = useLiveStocks(tickers);

  const corrMatrix = corrData.matrix;
  // No mock fallback — pairs missing from the live matrix (e.g. a ticker
  // dropped by the backend for insufficient price history) resolve to
  // null and are treated as "unknown", not filled with a fake value.
  const corr = useCallback((a, b) => corrMatrix?.[a]?.[b] ?? null, [corrMatrix]);
  const holdings = useMemo(() => etf?.holdings ?? [], [etf]);
  const layout = useMemo(() => computeLayout(etfId, holdings, corrMatrix), [etfId, holdings, corrMatrix]);

  const edges = useMemo(() => {
    const result = [];
    for (let i = 0; i < tickers.length; i++) {
      for (let j = i + 1; j < tickers.length; j++) {
        const v = corr(tickers[i], tickers[j]);
        if (v == null || v < threshold) continue;
        result.push({ a: tickers[i], b: tickers[j], v });
      }
    }
    return result;
  }, [tickers, threshold, corr]);

  // Guard against edges referencing tickers whose layout position isn't
  // ready yet (e.g. mid-transition while a new ETF's holdings load).
  const renderableEdges = useMemo(
    () => edges.filter(({ a, b }) => layout[a] && layout[b]),
    [edges, layout]
  );

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex-none flex items-center gap-3 mb-4">
        <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">edge ρ ≥</span>
        <input type="range" className="corr-range flex-1 max-w-[300px]" min={0.2} max={0.9} step={0.01} value={threshold} onInput={e => setThreshold(parseFloat(e.target.value))} />
        <span className="font-[var(--font-mono)] text-[13px] font-semibold text-[var(--fg)] w-9 tabular-nums">{fmtCorr(threshold)}</span>
        <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">· {corrData.loading ? '…' : edges.length} links</span>
      </div>

      {/* This view fetches its own copy of the ETF (see useLiveEtf), so it
          gates on that fetch itself — DetailAside below needs a loaded etf. */}
      {corrData.loading || etfLoading ? (
        <Loading variant="chart" height={440} />
      ) : !etf ? (
        <ErrorState onRetry={etfRetry} />
      ) : (
        <div className="flex-1 min-h-0 flex gap-5 items-start flex-wrap">
          <section className="flex-1 min-w-[320px] bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] overflow-hidden animate-[corrFadeUp_var(--dur-base)_var(--ease-out)]">
            <div className="p-2 pb-4 relative">
              <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="block" style={{ maxHeight: 460 }}>
                {/* Logo patterns */}
                <defs>
                  {tickers.map(t => {
                    const p = layout[t];
                    if (!p) return null;
                    const w = weightOf(t);
                    const r = nodeRadius(w);
                    const name = stockMap[t]?.name;
                    const pid = 'lp_' + t.replace('.', '_');
                    const pad = r * 0.14;
                    return (
                      <pattern key={pid} id={pid} x={p.x - r} y={p.y - r} width={r * 2} height={r * 2} patternUnits="userSpaceOnUse">
                        <rect width={r * 2} height={r * 2} fill="var(--bg-1)" />
                        <image
                          href={logoUrl(t, name)}
                          data-favicon-fallback={fallbackFaviconUrl(t, name)}
                          onError={handleSvgImageLogoError}
                          x={pad} y={pad} width={r * 2 - pad * 2} height={r * 2 - pad * 2} preserveAspectRatio="xMidYMid meet"
                        />
                      </pattern>
                    );
                  })}
                </defs>

                <rect x={0} y={0} width={W} height={H} fill="transparent" onClick={() => onSelect(null)} />

                {/* Edges */}
                {renderableEdges.map(({ a, b, v }) => {
                  const p1 = layout[a], p2 = layout[b];
                  const active = selected && (a === selected || b === selected);
                  const base = 0.10 + (v - threshold) * 0.85;
                  const op = selected ? (active ? 0.95 : 0.04) : base;
                  const sw = (0.7 + (v - threshold) * 5.5) * (active ? 1.5 : 1);
                  return <line key={`${a}-${b}`} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke="var(--accent)" strokeOpacity={op} strokeWidth={sw} strokeLinecap="round" />;
                })}

                {/* Nodes */}
                {tickers.map(t => {
                  const p = layout[t];
                  if (!p) return null;
                  const w = weightOf(t);
                  const r = nodeRadius(w);
                  const isSel = selected === t;
                  const peerRho = selected ? corr(selected, t) : null;
                  const isNb = selected && selected !== t && peerRho != null && peerRho >= threshold;
                  const dim = selected && !isSel && !isNb;
                  const pid = 'lp_' + t.replace('.', '_');
                  // Always a truthy pattern-url string — the SVG <pattern>
                  // defined above always exists for this ticker, so there's
                  // no fallback fill to fall back to.
                  const fill = `url(#${pid})`;
                  const stroke = isSel || isNb ? 'var(--accent)' : 'var(--border-strong)';
                  return (
                    <g key={t} style={{ cursor: 'pointer', opacity: dim ? 0.32 : 1, transition: 'opacity 200ms' }} onClick={e => { e.stopPropagation(); onSelect(t); }}>
                      {isSel && <circle cx={p.x} cy={p.y} r={r + 5} fill="none" stroke="var(--accent-ring)" strokeWidth={2} />}
                      <circle cx={p.x} cy={p.y} r={r} fill={fill} stroke={stroke} strokeWidth={isSel ? 2.2 : (isNb ? 1.8 : 1.6)} />
                      {isSel && <circle cx={p.x} cy={p.y} r={r} fill="var(--accent)" fillOpacity={0.28} />}
                      <text x={p.x} y={p.y + r + 13} textAnchor="middle" fill={isSel ? 'var(--accent)' : 'var(--fg-1)'} fontSize={11} fontWeight={600} fontFamily="var(--font-mono)">{t}</text>
                    </g>
                  );
                })}
              </svg>

              {/* Legend */}
              <div className="flex items-center gap-10 px-4 pt-3 flex-wrap">
                <span className="flex items-center gap-[7px] text-xs text-[var(--fg-2)]"><span className="w-3.5 h-3.5 rounded-full bg-[var(--bg-1)] border-[1.5px] border-[var(--border-strong)]" />node size = weight in fund</span>
                <span className="flex items-center gap-[7px] text-xs text-[var(--fg-2)]"><span className="w-[22px] h-[3px] rounded-full bg-[var(--accent)]" />line = correlation strength</span>
                <span className="text-xs text-[var(--fg-3)]">click a node to isolate its links</span>
              </div>
            </div>
          </section>

          <DetailAside etf={etf} tickers={tickers} selected={selected} onSelect={onSelect} correlationData={corrData} sectorData={sectors} />
        </div>
      )}
    </div>
  );
});
