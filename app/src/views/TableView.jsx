/**
 * TableView — filterable, sortable list of all ETF holdings.
 *
 * Columns are dynamic — built from whichever measurements are active.
 * Each measurement declares its column_label, column_width, filter
 * config (filter_type, filter_options, etc.), and sort config (sort_type,
 * sort_order). Cell content is real MDX/JSX the backend already rendered
 * (per_ticker_mdx), compiled and displayed via MdxCell — this view has no
 * per-measurement formatting logic, it just hosts whatever component
 * tree each measurement chose to render.
 *
 * Layout: the STOCK column has a fixed width and never wraps. The
 * measurement columns live in a flex-wrap row beside it, each pinned to
 * its own `column_width`. Because every row (header, filter row, and
 * every stock row) renders the exact same set of fixed-width cells in a
 * flex-wrap container, they all break onto a second line at the same
 * point — so a wide set of metrics grows the row height instead of
 * overflowing or losing alignment between columns.
 *
 * Sections (top to bottom):
 *  1. Toolbar row: Measurements button + search bar + shared window
 *     control (issue #101), shown only once some active column actually
 *     has a window to control
 *  2. Column headers: STOCK + one header per active measurement, each
 *     clickable to sort (ascending/descending toggle on repeat click) —
 *     a window-aware column's header also names its window, so two
 *     columns on screen never leave a reader guessing whether they
 *     describe the same stretch of history. A small dot beside the sort
 *     label is that column's own cost rating (issue #115) — Short
 *     through Extremely long, read off the live run's own `cost` once
 *     it has answered (rated against the window this column was just
 *     fetched with) or the manifest's own otherwise, so widening the
 *     shared window can visibly move a column from Short to Long without
 *     this view computing anything about cost itself
 *  3. Filter row: sector dropdown + per-measurement filters
 *  4. Scrollable rows: one row per holding, sorted per the active sort key
 */
import { memo, useState, useMemo, useCallback } from 'react';
import { useLiveStocks } from '../hooks/useLiveStocks';
import { Logo } from '../components/ui/Logo';
import { Loading } from '../components/ui/Loading';
import { MdxCell } from '../components/ui/MdxCell';
import { DocLink } from '../components/ui/DocLink';
import { CostBadge } from '../components/ui/CostBadge';
import { WINDOW_OPTIONS } from '../hooks/useMeasurementWindow';

const NAME_COL_WIDTH = 230;
const NAME_SORT_KEY = '__name__';

/** Whether any manifest row in `list` declares support for a window. */
function hasWindowAware(list) {
  return list.some(m => (m.window_options || []).length > 0);
}

/** A column's own window label for the currently active window — falls
 *  back to the column's own default's label if the shared value isn't
 *  among its (possibly narrower) options, matching how the backend
 *  itself degrades (base.run()'s fallback-to-default). */
function columnWindowLabel(m, window) {
  const options = m.window_options || [];
  const match = options.find(o => o.value === window);
  if (match) return match.label;
  return options.find(o => o.value === m.window_default)?.label ?? window;
}

export const TableView = memo(function TableView({
  tickers, onSelectStock,
  measurements, onOpenMeasurePicker,
  measurementWindow, onMeasurementWindowChange,
}) {
  const [query, setQuery] = useState('');
  const [filterSector, setFilterSector] = useState('');
  const [measureFilters, setMeasureFilters] = useState({});
  const [sort, setSort] = useState({ key: null, dir: 'asc' });

  const { stockMap, loading: stocksLoading, error: stocksError } = useLiveStocks(tickers);

  const sectorOptions = useMemo(
    () => [...new Set(tickers.map(t => stockMap[t]?.sector || 'Unknown'))].sort(),
    [tickers, stockMap]
  );

  const setMeasureFilter = useCallback((id, value) => {
    setMeasureFilters(prev => ({ ...prev, [id]: value }));
  }, []);

  const activeMeasures = measurements.activeManifests;
  // Shown only once some active column actually has a window to
  // control (issue #101) — a control that changes nothing today,
  // before any window-aware column exists, would just be clutter.
  const showWindowControl = hasWindowAware(activeMeasures);

  // If the measurement currently used for sorting gets deactivated, fall
  // back to unsorted rather than silently sorting by a stale/missing column.
  // Corrected during render (keyed off the active measurement id list)
  // rather than in an effect — see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const activeMeasureIds = activeMeasures.map(m => m.id).join(',');
  const [prevActiveMeasureIds, setPrevActiveMeasureIds] = useState(activeMeasureIds);
  if (activeMeasureIds !== prevActiveMeasureIds) {
    setPrevActiveMeasureIds(activeMeasureIds);
    if (sort.key && sort.key !== NAME_SORT_KEY && !activeMeasures.some(m => m.id === sort.key)) {
      setSort({ key: null, dir: 'asc' });
    }
  }

  const handleSortClick = useCallback((key, defaultDir) => {
    setSort(prev => prev.key === key
      ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: defaultDir });
  }, []);

  // Build rows with measurement values — mVals (raw) drives sort/filter,
  // mMdx (backend-rendered markdown) is what's actually displayed, mReason
  // (issue #99) is why a null value is null, when a measurement says.
  const allRows = useMemo(() => {
    return tickers.map(t => {
      const stock = stockMap[t] || { name: t, sector: 'Unknown' };
      const mVals = measurements.getTickerValues(t);
      const mMdx = measurements.getTickerMdx(t);
      const mReason = measurements.getTickerReason(t);
      return { ticker: t, name: stock.name, sector: stock.sector, mVals, mMdx, mReason };
    });
    // Deliberately narrowed to the functions actually called here, not the
    // whole `measurements` object — that object's other fields (e.g.
    // loading) change far more often and would invalidate this memo for
    // no reason.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickers, stockMap, measurements.getTickerValues, measurements.getTickerMdx, measurements.getTickerReason]);

  // Apply filters
  const filtered = useMemo(() => {
    const tq = query.trim().toLowerCase();
    return allRows
      .filter(r => !tq || r.ticker.toLowerCase().includes(tq) || r.name.toLowerCase().includes(tq) || r.sector.toLowerCase().includes(tq))
      .filter(r => !filterSector || r.sector === filterSector)
      .filter(r => {
        for (const m of activeMeasures) {
          if (!m.filterable) continue;
          const filterVal = measureFilters[m.id];
          if (filterVal === undefined || filterVal === 0 || filterVal === '') continue;
          const cellVal = r.mVals[m.id];
          if (cellVal === null || cellVal === undefined) return false;
          if (m.filter_type === 'range' || m.filter_type === 'choices') {
            if (cellVal < filterVal) return false;
          }
        }
        return true;
      });
  }, [allRows, query, filterSector, activeMeasures, measureFilters]);

  // Apply sort (stable — filtered order is preserved when unsorted)
  const sortedRows = useMemo(() => {
    if (!sort.key) return filtered;
    const manifest = sort.key === NAME_SORT_KEY ? null : activeMeasures.find(m => m.id === sort.key);
    if (sort.key !== NAME_SORT_KEY && !manifest) return filtered;
    return filtered.slice().sort((a, b) => compareRows(a, b, sort.key, sort.dir, manifest));
  }, [filtered, sort, activeMeasures]);

  const hasActiveFilters = !!(filterSector || Object.values(measureFilters).some(v => v > 0));

  const clearFilters = useCallback(() => {
    setFilterSector('');
    setMeasureFilters({});
  }, []);

  return (
    <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
      {/* ── Toolbar: measurements button + search ── */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={onOpenMeasurePicker}
          className="flex-none flex items-center gap-2 px-3.5 py-[9px] rounded-[var(--radius-md)] cursor-pointer text-sm transition-all duration-150 border"
          style={{
            background: activeMeasures.length > 0 ? 'var(--accent-soft)' : 'var(--bg-1)',
            borderColor: activeMeasures.length > 0 ? 'var(--accent-ring)' : 'var(--border)',
            color: activeMeasures.length > 0 ? 'var(--accent)' : 'var(--fg-2)',
            fontWeight: activeMeasures.length > 0 ? 600 : 500,
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 20V10M18 20V4M6 20v-4" />
          </svg>
          Metrics
          {activeMeasures.length > 0 && (
            <span className="font-[var(--font-mono)] text-[11px] bg-[var(--accent)] text-white rounded-full w-[18px] h-[18px] grid place-items-center">
              {activeMeasures.length}
            </span>
          )}
        </button>

        <div className="flex-1 max-w-[460px] flex items-center gap-2 h-[42px] px-3.5 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-md)] shadow-[var(--shadow-xs)]">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--fg-2)] flex-none"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
          <input value={query} onInput={e => setQuery(e.target.value)} placeholder="Search a holding — ticker, name, sector…" className="flex-1 border-none outline-none bg-transparent text-[var(--fg)] font-[var(--font-body)] text-sm" />
          <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-3)] flex-none">{sortedRows.length}/{tickers.length}</span>
        </div>

        {showWindowControl && (
          <MeasurementWindowControl window={measurementWindow} onChange={onMeasurementWindowChange} />
        )}
      </div>

      {/* ── Table ── */}
      <div className="flex-1 mb-4 min-h-0 overflow-hidden flex flex-col bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] px-1">
        {/* Column headers.

            Every inset here mirrors the data rows below rather than being
            chosen for the header on its own, so a header sits directly
            above the values it labels. A data row is a bordered button
            (1px) whose cells carry their own padding, so this row borrows
            the same 1px horizontally — transparent, since the header is
            not a card — and each slot repeats its cell's padding. */}
        <div className="flex items-start py-2 border-x border-transparent">
          <MetricSlot width={NAME_COL_WIDTH} className="pl-2">
            <SortHeader label="STOCK" active={sort.key === NAME_SORT_KEY} dir={sort.dir} onClick={() => handleSortClick(NAME_SORT_KEY, 'asc')} />
          </MetricSlot>
          <div className="flex-1 min-w-0 flex flex-wrap items-start">
            {activeMeasures.map(m => {
              const windowAware = (m.window_options || []).length > 0;
              const label = windowAware
                ? `${m.column_label} · ${columnWindowLabel(m, measurementWindow)}`
                : m.column_label;
              // The live run's own cost once it has answered (rated
              // against the *actual* window this plugin was just fetched
              // with, issue #115) — falling back to the manifest's own,
              // computed once at window_default, before that arrives.
              // This is what lets a window-aware column's dot move from
              // Short to Long as the shared control widens, with no
              // client-side scoring logic of its own to keep in sync
              // with measurements/cost.py.
              const liveCost = measurements.results[m.measurement_id]?.cost;
              return (
                <MetricSlot key={m.id} width={m.column_width} className="pl-2 border-l border-transparent">
                  {/* The "?" is a sibling of the sort button, not inside it:
                      reading about a column must not also re-sort it. */}
                  <div className="flex items-center gap-1.5">
                    <SortHeader label={label} active={sort.key === m.id} dir={sort.dir} onClick={() => handleSortClick(m.id, defaultDirFor(m))} />
                    <CostBadge cost={liveCost || m.cost} compact />
                    <DocLink measurementId={m.measurement_id} measurementName={m.name} />
                  </div>
                </MetricSlot>
              );
            })}
            {activeMeasures.length === 0 && (
              <div className="pl-4 font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] italic">
                No metrics selected — click "Metrics" to add columns
              </div>
            )}
          </div>
        </div>

        {/* Filter row */}
        <div className="flex items-stretch bg-[var(--bg-2)] border-t border-b border-[var(--divider)] rounded-xl overflow-hidden">
          <MetricSlot width={NAME_COL_WIDTH} className="flex items-center justify-center p-[5px_10px]">
            <select value={filterSector} onChange={e => setFilterSector(e.target.value)} className="font-[var(--font-mono)] text-[10px] text-[var(--fg-1)] bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-sm)] py-[3px] px-1 w-full cursor-pointer outline-none">
              <option value="">All sectors</option>
              {sectorOptions.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </MetricSlot>
          <div className="flex-1 min-w-0 flex flex-wrap">
            {activeMeasures.map(m => (
              <MetricSlot key={m.id} width={m.column_width} className="flex items-center justify-center p-[5px_10px] border-l border-[var(--divider)]">
                <MeasureFilter manifest={m} value={measureFilters[m.id] ?? 0} onChange={v => setMeasureFilter(m.id, v)} />
              </MetricSlot>
            ))}
            {hasActiveFilters && (
              <div className="flex-none flex items-center justify-center p-[5px_10px] border-l border-[var(--divider)]">
                <button onClick={clearFilters} className="font-[var(--font-mono)] text-[10px] text-[var(--accent)] bg-transparent border border-[var(--accent)] rounded-full py-[3px] px-2.5 cursor-pointer whitespace-nowrap">clear</button>
              </div>
            )}
          </div>
        </div>

        {/* Rows */}
        <div className="corr-scroll flex-1 overflow-y-auto flex flex-col gap-1.5 p-[6px_0_24px]">
          {stocksLoading && (
            <div className="px-[18px] py-4">
              <Loading variant="skeleton" lines={8} />
            </div>
          )}
          {!stocksLoading && stocksError && (
            <div className="py-14 text-center text-[var(--fg-2)] text-sm">
              Couldn't load holding details — backend unreachable.
            </div>
          )}
          {!stocksLoading && !stocksError && sortedRows.map(row => (
            <button key={row.ticker} onClick={() => onSelectStock(row.ticker)}
              className="flex items-center text-left cursor-pointer w-full bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] transition-all duration-150 hover:border-[var(--border-strong)]"
            >
              {/* Stock identity */}
              <MetricSlot width={NAME_COL_WIDTH} className="flex items-center gap-2.5 overflow-hidden p-2">
                <Logo ticker={row.ticker} name={row.name} size={32} />
                <div className="flex flex-col gap-0.5 min-w-0 overflow-hidden">
                  <div className="font-[var(--font-mono)] text-[15px] font-bold text-[var(--accent)] tracking-tight">{row.ticker}</div>
                  <div className="text-sm font-semibold text-[var(--fg)] whitespace-nowrap overflow-hidden text-ellipsis">{row.name}</div>
                  <span className="self-start text-[11px] text-[var(--fg-2)] bg-[var(--bg-3)] rounded-full px-2.5 py-0.5 mt-0.5 whitespace-nowrap">{row.sector}</span>
                </div>
              </MetricSlot>

              {/* Dynamic measurement columns — wrap onto a new line together, in sync with the header */}
              <div className="flex-1 min-w-0 flex flex-wrap items-center">
                {activeMeasures.map(m => (
                  <MetricSlot key={m.id} width={m.column_width} className="pl-2 pr-2 border-l border-[var(--divider)]">
                    <MdxCell mdx={row.mMdx[m.id]} loading={measurements.loading[m.id]} reason={row.mReason[m.id]} />
                  </MetricSlot>
                ))}
              </div>
            </button>
          ))}
          {!stocksLoading && !stocksError && sortedRows.length === 0 && (
            <div className="py-14 text-center text-[var(--fg-2)] text-sm">No holdings match the current filters.</div>
          )}
        </div>
      </div>
    </div>
  );
});


/**
 * MetricSlot — fixed-width cell used identically in the header, filter
 * row, and every data row. Because every row renders the same list of
 * slot widths inside a `flex flex-wrap` container of the same overall
 * width, they all wrap onto a second line at the same point, keeping
 * columns aligned across every row even as metrics are added or removed.
 */
function MetricSlot({ width, className = '', children }) {
  return (
    <div className={`flex-none box-border ${className}`} style={{ width: width + 'px' }}>
      {children}
    </div>
  );
}


/** Clickable column header showing the active sort direction, if any. */
function SortHeader({ label, active, dir, onClick }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1 font-[var(--font-mono)] text-[10px] bg-transparent border-none p-0 cursor-pointer transition-colors duration-150 hover:text-[var(--fg-1)]"
      style={{ color: active ? 'var(--accent)' : 'var(--fg-3)' }}
    >
      <span style={active ? { borderBottom: '2px solid var(--accent)', paddingBottom: 1 } : undefined}>{label}</span>
      {active && <span className="text-[9px] leading-none">{dir === 'asc' ? '▲' : '▼'}</span>}
    </button>
  );
}


/** Default sort direction for the first click on a column. */
function defaultDirFor(manifest) {
  if (!manifest || manifest.sort_type === 'alphabetical') return 'asc';
  return 'desc'; // numerical: biggest first · custom: sort_order as declared
}


/**
 * Compares two rows for the active sort key/direction.
 * Missing values always sort to the bottom, in either direction.
 */
function compareRows(a, b, sortKey, dir, manifest) {
  const mult = dir === 'asc' ? 1 : -1;

  if (sortKey === NAME_SORT_KEY) {
    return a.name.localeCompare(b.name) * mult;
  }
  if (!manifest) return 0;

  const aVal = a.mVals[sortKey];
  const bVal = b.mVals[sortKey];
  const aNull = aVal === null || aVal === undefined;
  const bNull = bVal === null || bVal === undefined;
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;

  if (manifest.sort_type === 'alphabetical') {
    return String(aVal).localeCompare(String(bVal)) * mult;
  }
  if (manifest.sort_type === 'custom' && manifest.sort_order?.length) {
    // sort_order is the descending order as declared; ascending is its reverse.
    const order = manifest.sort_order;
    const idxA = order.indexOf(aVal);
    const idxB = order.indexOf(bVal);
    const rankA = idxA === -1 ? order.length : idxA;
    const rankB = idxB === -1 ? order.length : idxB;
    return (rankA - rankB) * (dir === 'asc' ? -1 : 1);
  }
  return (aVal - bVal) * mult;
}


/**
 * MeasurementWindowControl — the one shared window every window-aware
 * column is computed over (issue #101). A segmented control rather than
 * a dropdown, matching WindowControls.jsx's own preset picker in the
 * portfolio simulator — the same idea, just without the two date boxes,
 * since a measurement window is always one of a fixed set of periods.
 */
function MeasurementWindowControl({ window, onChange }) {
  return (
    <div className="flex-none flex items-center gap-2">
      <span className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] uppercase tracking-wide">Window</span>
      <div className="inline-flex p-[3px] bg-[var(--bg-3)] rounded-[var(--radius-md)] gap-[1px]">
        {WINDOW_OPTIONS.map(option => {
          const active = window === option.value;
          return (
            <button
              key={option.value}
              onClick={() => onChange(option.value)}
              aria-pressed={active}
              className="px-2.5 py-[5px] border-none rounded-[7px] cursor-pointer font-[var(--font-mono)] text-xs transition-all duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
              style={{
                fontWeight: active ? 700 : 500,
                background: active ? 'var(--bg-1)' : 'transparent',
                color: active ? 'var(--fg)' : 'var(--fg-2)',
                boxShadow: active ? 'var(--shadow-xs)' : 'none',
              }}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}


/** Renders the filter control for a measurement based on its filter_type. */
function MeasureFilter({ manifest, value, onChange }) {
  if (!manifest.filterable || manifest.filter_type === 'none') return null;

  if (manifest.filter_type === 'choices') {
    return (
      <select value={value} onChange={e => onChange(parseFloat(e.target.value))}
        className="font-[var(--font-mono)] text-[10px] text-[var(--fg-1)] bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-sm)] py-[3px] px-1 w-full cursor-pointer outline-none">
        {(manifest.filter_options || []).map(opt => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    );
  }

  if (manifest.filter_type === 'range') {
    return (
      <div className="flex items-center gap-2 w-full">
        <span className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] flex-none">≥</span>
        <input type="range" className="corr-range flex-1" min={manifest.filter_min} max={manifest.filter_max} step={manifest.filter_step} value={value} onInput={e => onChange(parseFloat(e.target.value))} />
        <span className="font-[var(--font-mono)] text-[11px] font-semibold tabular-nums w-7 text-right" style={{ color: value > 0 ? 'var(--accent)' : 'var(--fg-3)' }}>{value.toFixed(2)}</span>
      </div>
    );
  }

  return null;
}
