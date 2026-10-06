/**
 * FullMatrix — the Full view's correlation matrix, every holding of a deep-filled
 * fund, on a canvas (issue #173).
 *
 * 250,000 cells are not 250,000 DOM nodes (the normal matrix's, which is why it
 * stops at the top 20): the whole matrix is one N × N bitmap, one pixel a cell
 * (`utils/fullMatrix.js`), built once per order and scaled by the canvas with
 * smoothing off, so a pan or zoom is a single `drawImage`. All the rules — the
 * order, which cluster blocks to outline, when a label can be read, which cell is
 * under the pointer — are that module's; this file paints what it returns.
 *
 * What it draws, from the outside in:
 *  - the colours alone while the matrix is zoomed out, as ρ and nothing else (the
 *    same ramp as the normal matrix; a pair with no correlation is a flat neutral,
 *    never a point on it);
 *  - a thin grid once cells are 8px, row and column tickers in the margins once they
 *    are 12px, and each ρ inside its cell once they are 34px;
 *  - an outline round each cluster's block on the diagonal and, when the block is
 *    big enough on screen, its name — neutral, never a hue;
 *  - clicking a stock (a cell, or a ticker in the margin) outlines its whole row and
 *    column and dims the rest; clicking it again clears it;
 *  - a tooltip with the hovered pair and its ρ.
 */
import { useCallback, useMemo, useState } from 'react';
import { ViewportCanvas } from './ViewportCanvas';
import { describeClusters } from '../../utils/clusters';
import { cellColor } from '../../utils/correlation';
import { fmtCorr } from '../../utils/format';
import { fmtWeight } from '../../utils/fullView';
import {
  arrange, cellPixels, cellAt, labelPlan, visibleCells, clusterBlocks, matrixLimits,
} from '../../utils/fullMatrix';
import { toWorld } from '../../utils/viewport';
import { tooltipPlacement } from '../../utils/tooltipPlacement';

/** Margins that hold the row and column tickers; fixed, like the normal matrix's. */
const LABEL_W = 64;
const HEADER_H = 64;
const FONT = '"JetBrains Mono", ui-monospace, monospace';
const GRID_MIN_CELL_PX = 8;
/** A cluster's name is written inside its block once the block is this wide on screen. */
const NAME_MIN_BLOCK_PX = 110;

const areaFor = (size) => ({
  x: LABEL_W,
  y: HEADER_H,
  w: Math.max(0, size.width - LABEL_W),
  h: Math.max(0, size.height - HEADER_H),
});

export function FullMatrix({ fund, order, within, selected, onSelect, colors }) {
  const { n } = fund;
  const content = useMemo(() => ({ w: n, h: n }), [n]);
  const arranged = useMemo(() => arrange(fund, order, within), [fund, order, within]);
  const blocks = useMemo(() => clusterBlocks(arranged.sections), [arranged]);
  const { clusterOf } = useMemo(() => describeClusters(fund.holdings, fund.clusters), [fund]);

  const tickerAt = useCallback((pos) => fund.tickers[arranged.order[pos]], [fund, arranged]);
  const selectedPos = useMemo(
    () => (selected == null ? -1 : arranged.order.indexOf(fund.indexOf.get(selected))),
    [selected, fund, arranged]
  );

  const bitmap = useMemo(() => {
    if (!colors) return null;
    const pixels = cellPixels(arranged.order, fund.corr, n, {
      ramp: colors.ramp, none: colors.none, diagonal: colors.diagonal,
    });
    const image = document.createElement('canvas');
    image.width = image.height = n;
    image.getContext('2d').putImageData(new ImageData(pixels, n, n), 0, 0);
    return image;
  }, [colors, arranged, fund, n]);

  const [hover, setHover] = useState(null);
  const hoverRow = hover?.row ?? -1;
  const hoverCol = hover?.col ?? -1;

  const handleHover = useCallback((p) => {
    if (!p || p.ax < 0 || p.ay < 0 || p.ax > p.area.w || p.ay > p.area.h) {
      setHover(null);
      return;
    }
    const cell = cellAt(p.view, p.ax, p.ay, n);
    setHover(cell ? { ...cell, x: p.x, y: p.y, width: p.width, height: p.height } : null);
  }, [n]);

  const handleTap = useCallback((p) => {
    let pos = null;
    if (p.ax >= 0 && p.ay >= 0) {
      const cell = cellAt(p.view, p.ax, p.ay, n);
      if (cell) pos = cell.col;
    } else if (p.ax < 0 && p.ay >= 0) {
      // A row ticker in the left margin.
      const row = Math.floor(toWorld(p.view, 0, p.ay).y);
      if (row >= 0 && row < n) pos = row;
    } else if (p.ay < 0 && p.ax >= 0) {
      // A column ticker in the top margin.
      const col = Math.floor(toWorld(p.view, p.ax, 0).x);
      if (col >= 0 && col < n) pos = col;
    }
    if (pos === null) return;
    const ticker = tickerAt(pos);
    onSelect(ticker === selected ? null : ticker);
  }, [n, tickerAt, selected, onSelect]);

  const draw = useCallback(({ ctx, size, area, view, colors: c }) => {
    if (!bitmap) return;
    const s = view.scale;
    const range = visibleCells(view, area, n);
    const plan = labelPlan(s);
    const cols = range.c1 - range.c0;
    const rows = range.r1 - range.r0;

    ctx.fillStyle = c.bg1;
    ctx.fillRect(0, 0, size.width, size.height);

    // ── The matrix, clipped to its area ──────────────────────────────────────
    ctx.save();
    ctx.beginPath();
    ctx.rect(area.x, area.y, area.w, area.h);
    ctx.clip();
    ctx.translate(area.x, area.y);

    const left = view.x + range.c0 * s;
    const top = view.y + range.r0 * s;
    if (cols > 0 && rows > 0) {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(bitmap, range.c0, range.r0, cols, rows, left, top, cols * s, rows * s);
    }

    if (s >= GRID_MIN_CELL_PX && cols > 0 && rows > 0) {
      ctx.strokeStyle = c.bg1;
      ctx.globalAlpha = 0.7;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let col = range.c0; col <= range.c1; col++) {
        const x = Math.round(view.x + col * s) + 0.5;
        ctx.moveTo(x, top);
        ctx.lineTo(x, top + rows * s);
      }
      for (let row = range.r0; row <= range.r1; row++) {
        const y = Math.round(view.y + row * s) + 0.5;
        ctx.moveTo(left, y);
        ctx.lineTo(left + cols * s, y);
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    if (plan.values) {
      ctx.font = `${plan.valuePx}px ${FONT}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (let r = range.r0; r < range.r1; r++) {
        const i = arranged.order[r];
        for (let col = range.c0; col < range.c1; col++) {
          const j = arranged.order[col];
          const v = fund.at(i, j);
          let text, fill;
          if (i === j) { text = '·'; fill = c.bg; }
          else if (v === null) { text = '—'; fill = c.fg3; }
          else { text = fmtCorr(v); fill = cellColor(v).fg === 'var(--accent-fg)' ? c.accentFg : c.fg; }
          ctx.fillStyle = fill;
          ctx.fillText(text, view.x + (col + 0.5) * s, view.y + (r + 0.5) * s);
        }
      }
    }

    // Cluster blocks on the diagonal: neutral outlines, and a name where there is room.
    ctx.strokeStyle = c.fg3;
    ctx.lineWidth = 1.5;
    for (const b of blocks) {
      ctx.strokeRect(view.x + b.start * s, view.y + b.start * s, b.count * s, b.count * s);
    }
    if (!plan.values) {
      ctx.font = `600 10.5px ${FONT}`;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      for (const b of blocks) {
        if (b.count * s < NAME_MIN_BLOCK_PX) continue;
        const bx = view.x + b.start * s;
        const by = view.y + b.start * s;
        // Pinned to the visible corner of the block, so the name stays readable while
        // the block's own corner is panned off screen.
        const x = Math.min(Math.max(bx, 0), bx + b.count * s - 8) + 4;
        const y = Math.min(Math.max(by, 0), by + b.count * s - 8) + 11;
        const text = `${b.label} · ${b.count}`;
        const width = ctx.measureText(text).width + 10;
        ctx.fillStyle = c.bg1;
        ctx.globalAlpha = 0.85;
        ctx.fillRect(x - 3, y - 9, width, 18);
        ctx.globalAlpha = 1;
        ctx.fillStyle = c.fg2;
        ctx.fillText(text, x + 2, y);
      }
    }

    // The selected stock: everything off its row and column dims, the cross is outlined.
    if (selectedPos >= 0) {
      const x0 = view.x, y0 = view.y, w = n * s, h = n * s;
      const rowY = y0 + selectedPos * s, colX = x0 + selectedPos * s;
      ctx.fillStyle = c.bg1;
      ctx.globalAlpha = 0.55;
      ctx.fillRect(x0, y0, w, rowY - y0);
      ctx.fillRect(x0, rowY + s, w, y0 + h - rowY - s);
      ctx.fillRect(x0, rowY, colX - x0, s);
      ctx.fillRect(colX + s, rowY, x0 + w - colX - s, s);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = c.accent;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x0, rowY, w, s);
      ctx.strokeRect(colX, y0, s, h);
    }

    if (hoverRow >= 0 && s >= 3) {
      ctx.strokeStyle = c.fg;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(view.x + hoverCol * s, view.y + hoverRow * s, s, s);
    }
    ctx.restore();

    // ── Tickers in the margins, once a cell is tall enough to carry one ──────
    if (plan.labels) {
      ctx.font = `${plan.labelPx}px ${FONT}`;
      ctx.textBaseline = 'middle';
      const style = (pos) => {
        ctx.fillStyle = pos === selectedPos ? c.accent : c.fg1;
        ctx.font = `${pos === selectedPos ? '700 ' : ''}${plan.labelPx}px ${FONT}`;
      };
      // Rows and columns are visible over different ranges once the matrix is panned.
      ctx.textAlign = 'right';
      for (let pos = range.r0; pos < range.r1; pos++) {
        const y = area.y + view.y + (pos + 0.5) * s;
        // A label whose row is scrolled half under the header would be drawn in it.
        if (y < area.y + 4 || y > area.y + area.h - 4) continue;
        style(pos);
        ctx.fillText(tickerAt(pos).slice(0, 8), area.x - 6, y);
      }
      ctx.textAlign = 'left';
      for (let pos = range.c0; pos < range.c1; pos++) {
        const x = area.x + view.x + (pos + 0.5) * s;
        if (x < area.x + 4 || x > area.x + area.w - 4) continue;
        style(pos);
        ctx.save();
        ctx.translate(x, area.y - 6);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText(tickerAt(pos).slice(0, 8), 0, 0);
        ctx.restore();
      }
    }
  }, [bitmap, fund, arranged, blocks, n, selectedPos, hoverRow, hoverCol, tickerAt]);

  let tooltip = null;
  if (hover) {
    const row = tickerAt(hover.row);
    const col = tickerAt(hover.col);
    const v = fund.at(arranged.order[hover.row], arranged.order[hover.col]);
    tooltip = (
      <div
        className="absolute z-10 pointer-events-none px-3 py-2 rounded-[var(--radius-md)] bg-[var(--bg-1)] border border-[var(--border-strong)] shadow-[var(--shadow-md)] font-[var(--font-mono)] text-xs text-[var(--fg-1)] whitespace-nowrap"
        style={{ top: Math.max(8, Math.min(hover.y + 14, hover.height - 90)), ...tooltipPlacement({ pctX: (hover.x / hover.width) * 100 }) }}
      >
        {row === col ? (
          <div className="font-semibold text-[var(--fg)]">{row}</div>
        ) : (
          <>
            <div className="font-semibold text-[var(--fg)]">{row} ↔ {col}</div>
            <div>ρ {v == null ? 'n/a — too little shared history' : fmtCorr(v)}</div>
          </>
        )}
        {[row, ...(row === col ? [] : [col])].map((t) => (
          <div key={t} className="text-[var(--fg-3)]">
            {t} · {fmtWeight(fund.weights[fund.indexOf.get(t)])} of the fund{clusterOf[t] ? ` · ${clusterOf[t].name}` : ''}
          </div>
        ))}
      </div>
    );
  }

  return (
    <ViewportCanvas
      content={content}
      areaFor={areaFor}
      limitsFor={matrixLimits}
      resetKey={`${fund.etfId}:${fund.asOf}`}
      colors={colors}
      draw={draw}
      onHover={handleHover}
      onTap={handleTap}
      cursor={hover ? 'pointer' : 'grab'}
      label={`Correlation matrix of ${n} holdings of ${fund.etfId}`}
    >
      {tooltip}
    </ViewportCanvas>
  );
}
