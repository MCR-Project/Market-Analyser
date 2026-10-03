/**
 * FullNetwork — the Full view's network of a deep-filled fund, every holding a
 * node, on a canvas (issue #173).
 *
 * The positions arrive already worked out (`useFullNetworkLayout`, once, in a
 * worker) and the Link Threshold arrives as a number: moving the slider changes
 * which links are drawn and nothing else. The links worth drawing are held sorted
 * strongest first (`utils/fullNetwork.js`), so a threshold is a prefix of that list
 * and the strength bands are slices of it, each drawn as one path.
 *
 * Nodes are sized by fund weight as in the normal network, but are plain circles:
 * five hundred logos would be five hundred image requests for a picture whose point
 * is the shape. A node's ticker is written only once the node is big enough on
 * screen to carry it, so a graph zoomed out is dots and lines and one zoomed in is
 * readable; the selected stock, its neighbours and the hovered node are always named.
 *
 * Clicking a node isolates it: everything not linked to it at the threshold dims and
 * its own links are drawn bold. Clicking the background clears it. Neutral colours
 * throughout, with the accent for links and for the selection — colour keeps meaning
 * correlation, as everywhere in this app.
 */
import { useCallback, useMemo, useState } from 'react';
import { ViewportCanvas } from './ViewportCanvas';
import { describeClusters } from '../../utils/clusters';
import { fmtCorr } from '../../utils/format';
import { fmtWeight } from '../../utils/fullView';
import {
  NETWORK_WORLD, nodeRadius, linksAtLeast, edgeBands,
  neighboursOf, hitNode, labelShown, networkLimits,
} from '../../utils/fullNetwork';
import { toWorld } from '../../utils/viewport';
import { tooltipPlacement } from '../../utils/tooltipPlacement';

const FONT = '"JetBrains Mono", ui-monospace, monospace';
const LABEL_PX = 11;

const areaFor = (size) => ({ x: 0, y: 0, w: size.width, h: size.height });

export function FullNetwork({ fund, positions, ranked, threshold, selected, onSelect, colors }) {
  const { n } = fund;
  const nodes = useMemo(
    () => ({ xs: positions.xs, ys: positions.ys, radii: Float32Array.from(fund.weights, nodeRadius) }),
    [positions, fund]
  );
  const drawn = useMemo(() => linksAtLeast(ranked, threshold), [ranked, threshold]);
  const bands = useMemo(() => edgeBands(ranked, threshold), [ranked, threshold]);
  const { clusterOf } = useMemo(() => describeClusters(fund.holdings, fund.clusters), [fund]);

  const selectedIdx = selected == null ? -1 : (fund.indexOf.get(selected) ?? -1);
  const neighbours = useMemo(
    () => (selectedIdx >= 0 ? neighboursOf(fund.corr, n, selectedIdx, threshold) : null),
    [fund, n, selectedIdx, threshold]
  );

  const [hover, setHover] = useState(null);
  const hoverIdx = hover?.i ?? -1;

  const handleHover = useCallback((p) => {
    if (!p) { setHover(null); return; }
    const w = toWorld(p.view, p.ax, p.ay);
    const i = hitNode(nodes, w.x, w.y, p.view.scale);
    setHover((prev) => {
      if (i === null) return prev === null ? prev : null;
      return { i, x: p.x, y: p.y, width: p.width, height: p.height };
    });
  }, [nodes]);

  const handleTap = useCallback((p) => {
    const w = toWorld(p.view, p.ax, p.ay);
    const i = hitNode(nodes, w.x, w.y, p.view.scale);
    onSelect(i === null || fund.tickers[i] === selected ? null : fund.tickers[i]);
  }, [nodes, fund, selected, onSelect]);

  const draw = useCallback(({ ctx, size, view, colors: c }) => {
    const s = view.scale;
    const { xs, ys, radii } = nodes;
    const px = (i) => view.x + xs[i] * s;
    const py = (i) => view.y + ys[i] * s;
    const focused = selectedIdx >= 0;

    ctx.fillStyle = c.bg1;
    ctx.fillRect(0, 0, size.width, size.height);

    // ── Links: one path per strength band ───────────────────────────────────
    ctx.lineCap = 'round';
    ctx.strokeStyle = c.accent;
    for (const band of bands) {
      ctx.beginPath();
      for (let k = band.start; k < band.end; k++) {
        const a = ranked.a[k], b = ranked.b[k];
        const x1 = px(a), y1 = py(a), x2 = px(b), y2 = py(b);
        if ((x1 < 0 && x2 < 0) || (x1 > size.width && x2 > size.width)
          || (y1 < 0 && y2 < 0) || (y1 > size.height && y2 > size.height)) continue;
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
      }
      ctx.globalAlpha = focused ? band.alpha * 0.12 : band.alpha;
      ctx.lineWidth = band.width;
      ctx.stroke();
    }
    if (focused) {
      ctx.beginPath();
      for (let k = 0; k < drawn; k++) {
        const a = ranked.a[k], b = ranked.b[k];
        if (a !== selectedIdx && b !== selectedIdx) continue;
        ctx.moveTo(px(a), py(a));
        ctx.lineTo(px(b), py(b));
      }
      ctx.globalAlpha = 0.9;
      ctx.lineWidth = 1.8;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    // ── Nodes ───────────────────────────────────────────────────────────────
    const named = [];
    for (let i = 0; i < n; i++) {
      const x = px(i), y = py(i);
      const r = Math.max(1.8, radii[i] * s);
      if (x < -r || x > size.width + r || y < -r || y > size.height + r) continue;

      const isSel = i === selectedIdx;
      const isNb = neighbours?.has(i) ?? false;
      const dim = focused && !isSel && !isNb && i !== hoverIdx;
      ctx.globalAlpha = dim ? 0.3 : 1;

      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      if (r < 4) {
        ctx.fillStyle = isSel || isNb ? c.accent : c.fg3;
        ctx.fill();
      } else {
        ctx.fillStyle = c.bg2;
        ctx.fill();
        ctx.lineWidth = isSel ? 2.2 : isNb ? 1.8 : 1.2;
        ctx.strokeStyle = isSel || isNb ? c.accent : c.borderStrong;
        ctx.stroke();
      }
      if (isSel) {
        ctx.beginPath();
        ctx.arc(x, y, r + 5, 0, Math.PI * 2);
        ctx.lineWidth = 2;
        ctx.strokeStyle = c.accent;
        ctx.globalAlpha = 0.5;
        ctx.stroke();
      }
      if (i === hoverIdx) {
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.arc(x, y, r + 2, 0, Math.PI * 2);
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = c.fg;
        ctx.stroke();
      }
      if (i === hoverIdx || isSel || isNb || (!dim && labelShown(radii[i], s))) named.push({ i, x, y, r, isSel });
    }
    ctx.globalAlpha = 1;

    // ── Tickers, drawn last so no node covers a label ───────────────────────
    ctx.font = `600 ${LABEL_PX}px ${FONT}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    for (const { i, x, y, r, isSel } of named) {
      ctx.fillStyle = isSel ? c.accent : c.fg1;
      ctx.fillText(fund.tickers[i], x, y + r + LABEL_PX + 2);
    }
  }, [nodes, ranked, bands, drawn, n, fund, selectedIdx, neighbours, hoverIdx]);

  let tooltip = null;
  if (hover) {
    const t = fund.tickers[hover.i];
    const linked = neighboursOf(fund.corr, n, hover.i, threshold).size;
    const rho = selectedIdx >= 0 && selectedIdx !== hover.i ? fund.at(hover.i, selectedIdx) : undefined;
    tooltip = (
      <div
        className="absolute z-10 pointer-events-none px-3 py-2 rounded-[var(--radius-md)] bg-[var(--bg-1)] border border-[var(--border-strong)] shadow-[var(--shadow-md)] font-[var(--font-mono)] text-xs text-[var(--fg-1)] whitespace-nowrap"
        style={{ top: Math.max(8, Math.min(hover.y + 14, hover.height - 100)), ...tooltipPlacement({ pctX: (hover.x / hover.width) * 100 }) }}
      >
        <div className="font-semibold text-[var(--fg)]">{t}</div>
        <div>{fmtWeight(fund.weights[hover.i])} of the fund{clusterOf[t] ? ` · ${clusterOf[t].name}` : ''}</div>
        <div className="text-[var(--fg-3)]">{linked} {linked === 1 ? 'link' : 'links'} at ρ ≥ {fmtCorr(threshold)}</div>
        {rho !== undefined && (
          <div>ρ with {selected}: {rho === null ? 'n/a' : fmtCorr(rho)}</div>
        )}
      </div>
    );
  }

  return (
    <ViewportCanvas
      content={NETWORK_WORLD}
      areaFor={areaFor}
      limitsFor={networkLimits}
      pad={16}
      resetKey={`${fund.etfId}:${fund.asOf}`}
      colors={colors}
      draw={draw}
      onHover={handleHover}
      onTap={handleTap}
      cursor={hover ? 'pointer' : 'grab'}
      label={`Network of ${n} holdings of ${fund.etfId}`}
    >
      {tooltip}
    </ViewportCanvas>
  );
}
