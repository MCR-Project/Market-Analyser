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
 */
import { memo, useState, useMemo, useCallback } from 'react';
import { useLiveEtf } from '../hooks/useLiveEtf';
import { useLiveCorrelation } from '../hooks/useLiveCorrelation';
import { useLiveSectors } from '../hooks/useLiveSectors';
import { cellColor } from '../utils/correlation';
import { fmtCorr } from '../utils/format';
import { DetailAside } from './DetailAside';
import { Loading } from '../components/ui/Loading';
import { ErrorState } from '../components/ui/ErrorState';

export const MatrixView = memo(function MatrixView({ selected, onSelect }) {
  const { etf, etfId, tickers, loading: etfLoading, retry: etfRetry } = useLiveEtf();
  // threshold=0 — the matrix always shows the full correlation range,
  // it doesn't filter by an edge threshold like the network view does.
  const corrData = useLiveCorrelation(etfId, tickers, 0);
  const sectors = useLiveSectors(etfId);

  const [matrixCount, setMatrixCount] = useState(10);
  const matrixCountMax = Math.min(20, tickers.length);
  const matrixN = Math.min(Math.max(5, matrixCount), matrixCountMax);

  const corrMatrix = corrData.matrix;
  // No mock fallback — a pair missing from the live matrix (e.g. a ticker
  // dropped by the backend for insufficient price history) resolves to
  // null and renders as "n/a", not a fake value.
  const corrFn = useCallback((a, b) => corrMatrix?.[a]?.[b] ?? null, [corrMatrix]);
  const matrixTickers = useMemo(() => tickers.slice(0, matrixN), [tickers, matrixN]);

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex-none flex items-center gap-3 mb-4">
        <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">stocks</span>
        <input type="range" className="corr-range flex-1 max-w-[300px]" min={5} max={matrixCountMax} step={1} value={matrixN} onInput={e => setMatrixCount(parseInt(e.target.value))} />
        <span className="font-[var(--font-mono)] text-[13px] font-semibold text-[var(--fg)] w-[22px] tabular-nums">{matrixN}</span>
      </div>

      {/* This view fetches its own copy of the ETF (see useLiveEtf), so it
          gates on that fetch itself — DetailAside below needs a loaded etf. */}
      {corrData.loading || etfLoading ? (
        <Loading variant="skeleton" lines={10} />
      ) : !etf ? (
        <ErrorState onRetry={etfRetry} />
      ) : (
        <div className="flex-1 min-h-0 flex gap-5 items-start flex-wrap">
          <section className="flex-1 min-w-[320px] min-h-0 max-h-full flex flex-col bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] overflow-hidden animate-[corrFadeUp_var(--dur-base)_var(--ease-out)]">
            <div className="flex-1 min-h-0 flex flex-col p-[18px_20px_20px]">
              <div className="corr-scroll flex-1 min-h-0 overflow-auto pb-1.5">
                <div className="inline-block min-w-full">
                  {/* Header — sticky so it stays visible while rows scroll vertically */}
                  <div className="flex sticky top-0 z-10 bg-[var(--bg-1)]">
                    <div className="w-[60px] flex-none" />
                    {matrixTickers.map(t => (
                      <div key={t} className="w-[44px] flex-none text-center font-[var(--font-mono)] text-[10px] font-semibold text-[var(--fg-2)] pb-2 overflow-hidden text-ellipsis">{t}</div>
                    ))}
                  </div>
                  {/* Rows */}
                  {matrixTickers.map(rt => {
                    const inSelRow = selected === rt;
                    return (
                      <div key={rt} className="flex items-center">
                        <button
                          onClick={() => onSelect(rt)}
                          className="w-[60px] flex-none text-right pr-2 font-[var(--font-mono)] text-[11px] bg-transparent border-none cursor-pointer h-[30px]"
                          style={{ fontWeight: inSelRow ? 700 : 500, color: inSelRow ? 'var(--accent)' : 'var(--fg-1)' }}
                        >
                          {rt}
                        </button>
                        {matrixTickers.map(ct => {
                          const v = corrFn(rt, ct);
                          const c = cellColor(v);
                          const isDiag = rt === ct;
                          const hi = selected && (rt === selected || ct === selected);
                          return (
                            <button
                              key={ct}
                              onClick={() => onSelect(ct === rt ? rt : ct)}
                              title={`${rt} ↔ ${ct}: ρ ${v == null ? 'n/a' : fmtCorr(v)}`}
                              className="w-[44px] h-[30px] flex-none grid place-items-center cursor-pointer font-[var(--font-mono)] text-[10.5px] border border-[var(--bg-1)] rounded-[3px] transition-opacity duration-150"
                              style={{
                                fontWeight: isDiag ? 700 : 500,
                                background: isDiag ? 'var(--fg-2)' : c.bg,
                                color: isDiag ? 'var(--bg)' : c.fg,
                                boxShadow: hi && !isDiag ? 'inset 0 0 0 1.5px var(--accent)' : 'none',
                                opacity: selected && !hi ? 0.45 : 1,
                              }}
                            >
                              {isDiag ? '·' : (v == null ? '—' : fmtCorr(v))}
                            </button>
                          );
                        })}
                      </div>
                    );
                  })}
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
            </div>
          </section>

          <DetailAside etf={etf} tickers={tickers} selected={selected} onSelect={onSelect} correlationData={corrData} sectorData={sectors} />
        </div>
      )}
    </div>
  );
});
