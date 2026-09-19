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
 * Layout comes from a 400-iteration force simulation run in the shape of
 * the graph's measured box (issue #139; cached per ETF and shape in
 * utils/layout.js), then fitted into that box: the panel fills the
 * height the view has, and the nodes spread across whatever width and
 * height that is. The SVG's viewBox is that same box in pixels, so a
 * node's radius and its label are the same size on any screen — a bigger box means more room between nodes, not
 * bigger nodes. It used to be a fixed 620×440 drawing scaled to fit,
 * which on a wide screen left a small graph in the middle of an empty
 * panel.
 *
 * Cluster outlines (issue #144), off by default (`?networkClusters=on`,
 * see useNetworkClusters): a soft dashed outline around each cluster the
 * backend found (issue #143), named after its heaviest holding exactly as
 * in the matrix (utils/clusters.js). Neutral tones, never a hue, so colour
 * keeps meaning correlation. The outline is a convex hull around the
 * members' circles and ticker labels (utils/clusterOutline.js); the layout
 * knows nothing about clusters, so a cluster whose members sit apart can
 * enclose a node that is not one of them — the outline says "these are
 * in it", not "only these are here". Each name is an HTML label over the
 * SVG, not SVG text, like the matrix's. With the toggle off none of this is
 * computed and the graph draws exactly as it always did.
 */
import { memo, useState, useMemo, useCallback } from 'react';
import { useLiveEtf } from '../hooks/useLiveEtf';
import { useLiveCorrelation } from '../hooks/useLiveCorrelation';
import { useLiveSectors } from '../hooks/useLiveSectors';
import { useLiveStocks } from '../hooks/useLiveStocks';
import { computeLayout } from '../utils/layout';
import { describeClusters } from '../utils/clusters';
import { clusterOutline } from '../utils/clusterOutline';
import { useElementSize } from '../hooks/useElementSize';
import { useNetworkClusters } from '../hooks/useNetworkClusters';
import { fmtCorr } from '../utils/format';
import { logoUrl, fallbackFaviconUrl, handleSvgImageLogoError } from '../utils/logo';
import { DetailAside } from './DetailAside';
import { Loading } from '../components/ui/Loading';
import { ErrorState } from '../components/ui/ErrorState';
import { SegmentedControl } from '../components/ui/SegmentedControl';

// Node radius bounds and reference weight (weightPct at/above which a
// node hits MAX_R). The curve is a genuine exponential (not sqrt/linear),
// so a 7% holding renders dramatically bigger than a 2% one — not just
// proportionally bigger — matching how a heavier position actually
// dominates the fund far more than its weight ratio alone suggests.
const MIN_R = 10, MAX_R = 60, REF_WEIGHT = 10, GROWTH = 4;
// A node's ticker sits 13px below its circle, 11px text: this much
// under a node keeps the label inside the box.
const LABEL_ROOM = 18;
// The ticker label's geometry, stated once for the <text> that draws it and
// the cluster outline that has to enclose it: 11px mono is about 6.6px a
// character, its baseline is 13px under the node's circle, and descenders
// take its bottom edge to about 16px under it.
const LABEL_FONT_SIZE = 11, LABEL_BASELINE = 13, LABEL_CHAR_W = 6.6;
const LABEL_BELOW = LABEL_BASELINE + 3;
// A cluster outline stands this far outside its members' circles and ticker
// labels.
const OUTLINE_PAD = 10;
// A cluster's name sits this far above its outline: the label's own height
// (10.5px text plus padding, about 17px) and a few pixels of air.
const NAME_ABOVE = 20;

const CLUSTER_OPTIONS = [
  { value: 'off', label: 'Off' },
  { value: 'on', label: 'On' },
];

function nodeRadius(weightPct) {
  const t = Math.min(1, Math.max(0, weightPct) / REF_WEIGHT);
  const curve = (Math.exp(GROWTH * t) - 1) / (Math.exp(GROWTH) - 1);
  return MIN_R + curve * (MAX_R - MIN_R);
}

export const NetworkView = memo(function NetworkView({ selected, onSelect }) {
  const { etf, etfId, tickers, weightOf, loading: etfLoading, retry: etfRetry } = useLiveEtf();
  const [threshold, setThreshold] = useState(0.5);
  const { showClusters, setShowClusters } = useNetworkClusters();
  const corrData = useLiveCorrelation(etfId);
  const sectors = useLiveSectors(etfId);
  const { stockMap } = useLiveStocks(tickers);

  const corrMatrix = corrData.matrix;
  // No mock fallback — pairs missing from the live matrix (e.g. a ticker
  // dropped by the backend for insufficient price history) resolve to
  // null and are treated as "unknown", not filled with a fake value.
  const corr = useCallback((a, b) => corrMatrix?.[a]?.[b] ?? null, [corrMatrix]);
  const holdings = useMemo(() => etf?.holdings ?? [], [etf]);
  const [boxRef, { width: W, height: H }] = useElementSize();
  const layout = useMemo(
    // Room for the largest node at the edge, plus its label below it.
    // Nothing until the box is measured: a layout for a 0×0 box is a full
    // simulation (55-140ms) whose result is thrown away a frame later.
    () => (W > 0 && H > 0 ? computeLayout(etfId, holdings, corrMatrix, W, H, MAX_R + LABEL_ROOM) : {}),
    [etfId, holdings, corrMatrix, W, H]
  );

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

  // One outline per cluster, only when asked for. A member with no layout
  // position yet is left out for the same reason as above, and a cluster
  // left with fewer than two drawn members gets no outline at all.
  const outlines = useMemo(() => {
    if (!showClusters) return [];
    return describeClusters(holdings, corrData.clusters).list.flatMap(cluster => {
      const nodes = cluster.members.filter(t => layout[t]).map(t => {
        const r = nodeRadius(weightOf(t));
        return {
          x: layout[t].x, y: layout[t].y, r,
          labelHalfWidth: (LABEL_CHAR_W * t.length) / 2, labelDepth: r + LABEL_BELOW,
        };
      });
      // Bounded by the box: the layout leaves room for a node and its label
      // but not for the outline's padding around a very heavy node at the edge.
      const outline = clusterOutline(nodes, OUTLINE_PAD, { minX: 1, minY: 1, maxX: W - 1, maxY: H - 1 });
      return outline ? [{ key: cluster.key, name: cluster.name, count: nodes.length, ...outline }] : [];
    });
  }, [showClusters, holdings, corrData.clusters, layout, weightOf, W, H]);

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex-none flex items-center gap-x-3 gap-y-2 mb-4 flex-wrap">
        <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">edge ρ ≥</span>
        <input type="range" className="corr-range flex-1 max-w-[300px]" min={0.2} max={0.9} step={0.01} value={threshold} onInput={e => setThreshold(parseFloat(e.target.value))} />
        <span className="font-[var(--font-mono)] text-[13px] font-semibold text-[var(--fg)] w-9 tabular-nums">{fmtCorr(threshold)}</span>
        <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">· {corrData.loading ? '…' : edges.length} links</span>
        <SegmentedControl label="clusters" options={CLUSTER_OPTIONS} value={showClusters ? 'on' : 'off'} onChange={value => setShowClusters(value === 'on')} />
      </div>

      {/* This view fetches its own copy of the ETF (see useLiveEtf), so it
          gates on that fetch itself — DetailAside below needs a loaded etf. */}
      {corrData.loading || etfLoading ? (
        <Loading variant="chart" height={440} />
      ) : !etf ? (
        <ErrorState onRetry={etfRetry} />
      ) : (
        <div className="flex-1 min-h-0 flex gap-5 items-start flex-wrap">
          {/* Stretched to the view's full height, unlike DetailAside beside
              it, which stays as tall as its own content. The minimum is
              the smallest box the graph still reads in; below it the page
              scrolls rather than squashing the nodes together. */}
          <section className="self-stretch flex-1 min-w-[320px] min-h-[380px] flex flex-col bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] overflow-hidden animate-[corrFadeUp_var(--dur-base)_var(--ease-out)]">
            <div className="flex-1 min-h-0 flex flex-col p-2 pb-4">
              {/* Sized by the section, never by the drawing: the SVG is
                  absolutely positioned, so drawing at the measured size
                  cannot grow the box it was measured from. */}
              <div ref={boxRef} className="flex-1 min-h-0 relative">
                {W > 0 && H > 0 && (
                  <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="absolute inset-0 block">
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

                    {/* Cluster outlines — under the edges and nodes, and inert
                        so a click on one still deselects like the background. */}
                    {outlines.map(o => (
                      <path
                        key={o.key}
                        d={o.path}
                        fill="var(--fg-3)"
                        fillOpacity={0.07}
                        stroke="var(--fg-3)"
                        strokeOpacity={0.55}
                        strokeWidth={1.25}
                        strokeDasharray="5 4"
                        strokeLinejoin="round"
                        pointerEvents="none"
                      />
                    ))}

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
                          <text x={p.x} y={p.y + r + LABEL_BASELINE} textAnchor="middle" fill={isSel ? 'var(--accent)' : 'var(--fg-1)'} fontSize={LABEL_FONT_SIZE} fontWeight={600} fontFamily="var(--font-mono)">{t}</text>
                        </g>
                      );
                    })}
                  </svg>
                )}
                {/* Cluster names: HTML over the SVG, like the matrix's labels. */}
                {outlines.map(o => (
                  <div
                    key={o.key}
                    className="absolute pointer-events-none -translate-x-1/2 whitespace-nowrap rounded-[4px] px-1.5 py-px font-[var(--font-mono)] text-[10.5px] font-semibold text-[var(--fg-2)]"
                    style={{ left: o.centerX, top: Math.max(2, o.top - NAME_ABOVE), background: 'color-mix(in oklab, var(--bg-1) 82%, transparent)' }}
                  >
                    {o.name} <span className="font-medium text-[var(--fg-3)]">· {o.count}</span>
                  </div>
                ))}
              </div>

              {/* Legend */}
              <div className="flex items-center gap-10 px-4 pt-3 flex-wrap">
                <span className="flex items-center gap-[7px] text-xs text-[var(--fg-2)]"><span className="w-3.5 h-3.5 rounded-full bg-[var(--bg-1)] border-[1.5px] border-[var(--border-strong)]" />node size = weight in fund</span>
                <span className="flex items-center gap-[7px] text-xs text-[var(--fg-2)]"><span className="w-[22px] h-[3px] rounded-full bg-[var(--accent)]" />line = correlation strength</span>
                {showClusters && (
                  <span className="flex items-center gap-[7px] text-xs text-[var(--fg-2)]"><span className="w-[22px] h-3 rounded-[4px] border-[1.5px] border-dashed border-[var(--fg-3)]" />outline = cluster: moved together over the past year, not a sector</span>
                )}
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
