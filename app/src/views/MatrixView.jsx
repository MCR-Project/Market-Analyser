/**
 * MatrixView — NxN correlation heatmap tab.
 *
 * Fully self-contained: fetches the active ETF's tickers, correlation
 * matrix, and sector breakdown itself, and owns its own "stocks" count
 * toolbar and DetailAside panel. Only `selected`/`onSelect` are passed
 * in from the parent, since the highlighted stock is shared with
 * NetworkView and must survive switching between the two tabs.
 *
 * Each cell is color-coded by correlation intensity (accent color at varying
 * opacity). Diagonal cells show "·". Clicking a cell or row label selects
 * that stock, which highlights its row/column and updates DetailAside.
 *
 * Below the grid: a gradient legend bar (0.0 → 1.0) and explanatory label.
 *
 * Cells grow into the space the panel has (issue #139): the panel fills
 * the view's height, and each cell takes an equal share of the measured
 * grid area, between its old fixed 44×30 and a ceiling past which a cell
 * is just a bigger coloured block. More room makes the same N tickers
 * easier to read; it never shows more of them — the slider decides N.
 * When the area is smaller than N minimum-size cells, the grid scrolls,
 * as it always did.
 *
 * Order and clusters (issue #143): the N tickers are drawn in cluster
 * order by default — holdings whose returns moved together sit together,
 * each group outlined on the diagonal and named after its heaviest
 * holding — or alphabetical, or by weight (`?matrixOrder=`, and inside a
 * cluster `?matrixWithin=`; see `useMatrixOrder`). All the ordering and
 * grouping rules live in `utils/matrixOrder.js`; this file only draws
 * what that returns. Colour keeps meaning ρ and nothing else, so the
 * clusters are shown with neutral outlines, gaps and labels, never a hue.
 * In the two other orders there are no blocks to outline, so a clustered
 * ticker carries a small neutral dot on its labels instead (accent when it
 * shares a cluster with the selected stock; hover for the cluster's name).
 */
import { memo, useState, useMemo, useCallback, Fragment } from 'react';
import { useLiveEtf } from '../hooks/useLiveEtf';
import { useLiveCorrelation } from '../hooks/useLiveCorrelation';
import { useLiveSectors } from '../hooks/useLiveSectors';
import { useMatrixOrder } from '../hooks/useMatrixOrder';
import { cellColor } from '../utils/correlation';
import { fmtCorr } from '../utils/format';
import { orderMatrix } from '../utils/matrixOrder';
import { useElementSize } from '../hooks/useElementSize';
import { DetailAside } from './DetailAside';
import { Loading } from '../components/ui/Loading';
import { ErrorState } from '../components/ui/ErrorState';
import { SegmentedControl } from '../components/ui/SegmentedControl';

/** Row-label column width and header-row height, both fixed — only the
 *  cells grow. The header row is given exactly HEADER_H (style below), not
 *  left to be as tall as its text: its content is one line of 10px text plus
 *  padding, 23px, and the cluster frames are positioned from HEADER_H — when
 *  this was only an upper bound the frames sat 3px low (issue #143). The
 *  labels never wrap (a long ticker is cut with an ellipsis instead), so 26
 *  always holds. If the header could grow, a grid sized to fit exactly
 *  would overflow, and the scrollbar that appeared would change the
 *  width the cells are sized from. */
const LABEL_W = 60;
const HEADER_H = 26;
const CELL_MIN_W = 44, CELL_MAX_W = 96;
const CELL_MIN_H = 30, CELL_MAX_H = 60;
/** In cluster order each section gets a label row above its rows and a gap
 *  before its columns. Both are fixed sizes, like the label column and the
 *  header, and are taken out of the box *before* the cells share the rest
 *  — otherwise a grid sized to fit exactly would overflow (see above). */
const SECTION_LABEL_H = 20;
const SECTION_GAP = 8;

const ORDER_OPTIONS = [
  { value: 'cluster', label: 'Cluster' },
  { value: 'alpha', label: 'A–Z' },
  { value: 'weight', label: 'Weight' },
];
const WITHIN_OPTIONS = [
  { value: 'weight', label: 'Weight' },
  { value: 'alpha', label: 'A–Z' },
];

const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, value));

/** A neutral dot marking a clustered ticker in the orders that draw no blocks. */
function ClusterDot({ shared }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block w-[5px] h-[5px] rounded-full mr-1.5 align-middle"
      style={{ background: shared ? 'var(--accent)' : 'var(--fg-3)' }}
    />
  );
}

export const MatrixView = memo(function MatrixView({ selected, onSelect }) {
  const { etf, etfId, tickers, loading: etfLoading, retry: etfRetry } = useLiveEtf();
  // The matrix always shows the full correlation range, it doesn't
  // filter by an edge threshold like the network view does.
  const corrData = useLiveCorrelation(etfId);
  const sectors = useLiveSectors(etfId);
  const { order, within, setOrder, setWithin } = useMatrixOrder();

  const [matrixCount, setMatrixCount] = useState(10);
  const matrixCountMax = Math.min(20, tickers.length);
  const matrixN = Math.min(Math.max(5, matrixCount), matrixCountMax);

  const corrMatrix = corrData.matrix;
  // No mock fallback — a pair missing from the live matrix (e.g. a ticker
  // dropped by the backend for insufficient price history) resolves to
  // null and renders as "n/a", not a fake value.
  const corrFn = useCallback((a, b) => corrMatrix?.[a]?.[b] ?? null, [corrMatrix]);

  const holdings = useMemo(() => etf?.holdings ?? [], [etf]);
  const { tickers: matrixTickers, sections, clusterOf } = useMemo(
    () => orderMatrix({ holdings, clusters: corrData.clusters, averages: corrData.averages, n: matrixN, order, within }),
    [holdings, corrData.clusters, corrData.averages, matrixN, order, within]
  );
  const sectionAt = useMemo(() => new Map((sections ?? []).map(s => [s.start, s])), [sections]);
  const sectionCount = sections?.length ?? 0;
  const selectedCluster = selected ? clusterOf[selected]?.name : null;

  const [gridRef, grid] = useElementSize();
  const cellW = clamp(
    Math.floor((grid.width - LABEL_W - Math.max(0, sectionCount - 1) * SECTION_GAP) / matrixN),
    CELL_MIN_W, CELL_MAX_W
  );
  // Never taller than wide: a tall narrow cell reads as a bar, not a square.
  const cellH = clamp(
    Math.floor((grid.height - HEADER_H - sectionCount * SECTION_LABEL_H) / matrixN),
    CELL_MIN_H, Math.min(CELL_MAX_H, cellW)
  );
  // Past about 60×40 a cell has room for a larger figure; below it the
  // old 10.5px is what fits "−0.12" inside a 44px cell.
  const roomy = cellW >= 60 && cellH >= 40;

  // Dots stand in for the blocks in the two orders that draw none.
  const showDots = order !== 'cluster';
  const dotFor = t => showDots && clusterOf[t]
    ? <ClusterDot shared={selectedCluster != null && clusterOf[t].name === selectedCluster} />
    : null;
  const labelTitle = t => (clusterOf[t] ? `${t} · ${clusterOf[t].name}` : t);

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex-none flex items-center gap-x-3 gap-y-2 mb-4 flex-wrap">
        <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">stocks</span>
        <input type="range" className="corr-range flex-1 max-w-[300px]" min={5} max={matrixCountMax} step={1} value={matrixN} onInput={e => setMatrixCount(parseInt(e.target.value))} />
        <span className="font-[var(--font-mono)] text-[13px] font-semibold text-[var(--fg)] w-[22px] tabular-nums">{matrixN}</span>
        <SegmentedControl label="order" options={ORDER_OPTIONS} value={order} onChange={setOrder} />
        {order === 'cluster' && (
          <SegmentedControl label="within" options={WITHIN_OPTIONS} value={within} onChange={setWithin} />
        )}
      </div>

      {/* This view fetches its own copy of the ETF (see useLiveEtf), so it
          gates on that fetch itself — DetailAside below needs a loaded etf. */}
      {corrData.loading || etfLoading ? (
        <Loading variant="skeleton" lines={10} />
      ) : !etf ? (
        <ErrorState onRetry={etfRetry} />
      ) : (
        <div className="flex-1 min-h-0 flex gap-5 items-start flex-wrap">
          {/* Stretched to the view's full height, and never below the
              smallest box the grid reads in: on a short screen the page
              scrolls rather than squeezing the matrix into a strip one
              row tall (issue #139 — the network view's own minimum). */}
          <section className="self-stretch flex-1 min-w-[320px] min-h-[380px] flex flex-col bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] overflow-hidden animate-[corrFadeUp_var(--dur-base)_var(--ease-out)]">
            <div className="flex-1 min-h-0 flex flex-col p-[18px_20px_20px]">
              {/* The scrollbar gutter is reserved whether or not there is
                  a scrollbar, so one appearing cannot change the width
                  the cells were just sized from. */}
              <div ref={gridRef} className="corr-scroll flex-1 min-h-0 overflow-auto pb-1.5 [scrollbar-gutter:stable]">
                <div className="relative inline-block min-w-full">
                  {/* Header — sticky so it stays visible while rows scroll vertically */}
                  <div className="flex sticky top-0 z-10 bg-[var(--bg-1)]" style={{ height: HEADER_H }}>
                    <div className="flex-none" style={{ width: LABEL_W }} />
                    {matrixTickers.map((t, i) => (
                      <div
                        key={t}
                        style={{ width: cellW, marginLeft: i > 0 && sectionAt.has(i) ? SECTION_GAP : 0 }}
                        className="flex-none text-center font-[var(--font-mono)] text-[10px] font-semibold text-[var(--fg-2)] pb-2 overflow-hidden text-ellipsis whitespace-nowrap"
                        title={labelTitle(t)}
                      >
                        {dotFor(t)}{t}
                      </div>
                    ))}
                  </div>
                  {/* Rows */}
                  {matrixTickers.map((rt, r) => {
                    const inSelRow = selected === rt;
                    const section = sectionAt.get(r);
                    return (
                      <Fragment key={rt}>
                        {section && (
                          <div
                            className="flex items-end font-[var(--font-mono)] text-[10.5px] font-semibold text-[var(--fg-2)] whitespace-nowrap overflow-hidden"
                            style={{ height: SECTION_LABEL_H }}
                          >
                            {section.kind === 'cluster' && (
                              <span aria-hidden="true" className="inline-block w-[2px] h-[11px] mr-1.5 mb-px bg-[var(--fg-3)]" />
                            )}
                            {section.label}
                            {section.kind === 'cluster' && (
                              <span className="font-medium text-[var(--fg-3)] ml-1.5">
                                · {section.count === section.size ? section.count : `${section.count} of ${section.size}`}
                              </span>
                            )}
                          </div>
                        )}
                        <div className="flex items-center">
                          <button
                            onClick={() => onSelect(rt)}
                            title={labelTitle(rt)}
                            className="flex-none text-right pr-2 font-[var(--font-mono)] text-[11px] bg-transparent border-none cursor-pointer"
                            style={{ width: LABEL_W, height: cellH, fontWeight: inSelRow ? 700 : 500, color: inSelRow ? 'var(--accent)' : 'var(--fg-1)' }}
                          >
                            {dotFor(rt)}{rt}
                          </button>
                          {matrixTickers.map((ct, c) => {
                            const v = corrFn(rt, ct);
                            const col = cellColor(v);
                            const isDiag = rt === ct;
                            const hi = selected && (rt === selected || ct === selected);
                            return (
                              <button
                                key={ct}
                                onClick={() => onSelect(ct === rt ? rt : ct)}
                                title={`${rt} ↔ ${ct}: ρ ${v == null ? 'n/a' : fmtCorr(v)}`}
                                className="flex-none grid place-items-center cursor-pointer font-[var(--font-mono)] border border-[var(--bg-1)] rounded-[3px] transition-opacity duration-150"
                                style={{
                                  width: cellW,
                                  height: cellH,
                                  marginLeft: c > 0 && sectionAt.has(c) ? SECTION_GAP : 0,
                                  fontSize: roomy ? 12.5 : 10.5,
                                  fontWeight: isDiag ? 700 : 500,
                                  background: isDiag ? 'var(--fg-2)' : col.bg,
                                  color: isDiag ? 'var(--bg)' : col.fg,
                                  boxShadow: hi && !isDiag ? 'inset 0 0 0 1.5px var(--accent)' : 'none',
                                  opacity: selected && !hi ? 0.45 : 1,
                                }}
                              >
                                {isDiag ? '·' : (v == null ? '—' : fmtCorr(v))}
                              </button>
                            );
                          })}
                        </div>
                      </Fragment>
                    );
                  })}
                  {/* One outline per cluster block on the diagonal. "Others"
                      and "No history" are bands, not blocks — nothing binds
                      their members to one another — so they get no frame. */}
                  {(sections ?? []).map((s, si) => s.kind !== 'cluster' ? null : (
                    <div
                      key={s.key}
                      aria-hidden="true"
                      className="absolute pointer-events-none rounded-[4px] border-[1.5px] border-[var(--fg-3)]"
                      style={{
                        left: LABEL_W + s.start * cellW + si * SECTION_GAP,
                        top: HEADER_H + (si + 1) * SECTION_LABEL_H + s.start * cellH,
                        width: s.count * cellW,
                        height: s.count * cellH,
                      }}
                    />
                  ))}
                </div>
              </div>

              {/* Legend */}
              <div className="flex-none flex items-center gap-3 mt-4 pt-3.5 border-t border-[var(--divider)]">
                <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-2)]">CORRELATION</span>
                <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">0.0</span>
                <div className="flex-1 max-w-[220px] h-2 rounded-full border border-[var(--border)]" style={{ background: 'linear-gradient(90deg, var(--bg-1), color-mix(in oklab, var(--accent) 92%, var(--bg-1)))' }} />
                <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">1.0</span>
                <span className="flex-1" />
                <span className="text-xs text-[var(--fg-3)]">Pearson ρ of daily returns · click a cell to inspect</span>
              </div>
              <p className="flex-none mt-2 text-xs text-[var(--fg-3)]">
                Clusters group stocks whose returns moved together over the past year. They are not sectors.
              </p>
            </div>
          </section>

          <DetailAside etf={etf} tickers={tickers} selected={selected} onSelect={onSelect} correlationData={corrData} sectorData={sectors} />
        </div>
      )}
    </div>
  );
});
