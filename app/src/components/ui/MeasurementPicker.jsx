/**
 * MeasurementPicker — dialog to toggle which measurement columns are
 * displayed.
 *
 * The manifest has one entry per *column*, not per plugin (issue #100):
 * a plugin providing several columns from one computation groups them
 * under one header (its name, description, schema preview and doc link,
 * shown once) with one toggle row per column beneath it — so a reader
 * never has to think about which plugin a column comes from, only
 * whether they want it. A single-column plugin — every official one,
 * today — renders exactly as every measurement always has: the whole
 * row is the toggle, name and description included, because grouping a
 * plugin's columns has nothing to add when there is only one.
 *
 * `AttributionCard` (issue #114) sits beneath the schema preview in
 * either layout, reading straight off the manifest — every row already
 * carries the plugin's resolved `author`/`author_url`/`version`
 * (`backend/measurements/registry.py`'s `_column_manifest_entries`), so
 * "who wrote this and what does it provide" needs no extra fetch.
 *
 *  ┌─────────────────────────────────────────┐
 *  │ MEASUREMENTS                            │
 *  │ Select which metrics to compute         │
 *  ├─────────────────────────────────────────┤
 *  │ [X] Pairwise Correlation             ?  │  ← single-column plugin:
 *  │     Pearson ρ of daily returns...       │    the row is the toggle
 *  │     Inputs: etf_id, period, threshold   │
 *  │     Outputs: matrix, averages, hub...   │
 *  │     Official · Jane Doe · v1.0          │
 *  ├─────────────────────────────────────────┤
 *  │ Capture Ratio                        ?  │  ← multi-column plugin:
 *  │ How much of the benchmark's...          │    header, then one
 *  │ Official · Jane Doe · Provides 2: …     │    toggle row per column
 *  │ [X] Upside Capture                      │
 *  │ [ ] Downside Capture                    │
 *  └─────────────────────────────────────────┘
 */
import { memo, useMemo } from 'react';
import { Overlay } from './Overlay';
import { DocLink } from './DocLink';
import { AttributionCard } from './AttributionCard';

/** A plugin's shared info: name, description, and its input/output
 * schema preview — identical across every column it provides, so shown
 * once per group rather than once per column. */
function SchemaPreview({ plugin }) {
  const inputKeys = Object.keys(plugin.input_schema || {});
  const outputKeys = Object.keys(plugin.output_schema || {});
  if (inputKeys.length === 0 && outputKeys.length === 0) return null;

  return (
    <div className="flex gap-4 flex-wrap">
      {inputKeys.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="font-[var(--font-mono)] text-[9px] text-[var(--fg-3)] uppercase tracking-wide">In</span>
          {inputKeys.map(k => (
            <span key={k} className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] bg-[var(--bg-3)] rounded px-1.5 py-0.5">{k}</span>
          ))}
        </div>
      )}
      {outputKeys.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="font-[var(--font-mono)] text-[9px] text-[var(--fg-3)] uppercase tracking-wide">Out</span>
          {outputKeys.slice(0, 4).map(k => (
            <span key={k} className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] bg-[var(--bg-3)] rounded px-1.5 py-0.5">{k}</span>
          ))}
          {outputKeys.length > 4 && (
            <span className="font-[var(--font-mono)] text-[10px] text-[var(--fg-3)]">+{outputKeys.length - 4}</span>
          )}
        </div>
      )}
    </div>
  );
}

/** The toggle indicator square, active or not — shared by both layouts
 * below so a checked column looks identical whichever one renders it. */
function ToggleIndicator({ active }) {
  return (
    <div className="flex-none w-5 h-5 rounded-[var(--radius-xs)] border-2 grid place-items-center transition-colors duration-150"
      style={{
        borderColor: active ? 'var(--accent)' : 'var(--border-strong)',
        background: active ? 'var(--accent)' : 'transparent',
      }}
    >
      {active && (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 6 9 17l-5-5" />
        </svg>
      )}
    </div>
  );
}

/** A single-column plugin (every official one, today): the whole row is
 * the toggle, exactly as every measurement rendered before issue #100. */
function SingleColumnRow({ column, active, onToggle }) {
  return (
    <div
      className="flex items-start border-b border-[var(--divider)] transition-colors duration-150"
      style={{ background: active ? 'var(--accent-soft)' : 'transparent' }}
    >
      {/* The row is a wrapper, not a button: the "?" that opens this
          measurement's documentation has to be a sibling of the toggle,
          since an anchor cannot live inside a button — and reading about
          a measurement must not also switch it on. */}
      <button
        onClick={() => onToggle(column.id)}
        aria-pressed={active}
        className="flex items-start gap-4 flex-1 min-w-0 p-5 pr-2 text-left cursor-pointer bg-transparent border-none"
      >
        <div className="mt-0.5"><ToggleIndicator active={active} /></div>
        <div className="flex-1 min-w-0">
          <div className="text-[15px] font-semibold text-[var(--fg)] mb-1">{column.name}</div>
          <p className="text-[13px] text-[var(--fg-2)] m-0 leading-relaxed mb-2">{column.description}</p>
          <SchemaPreview plugin={column} />
          <div className="mt-2">
            <AttributionCard
              author={column.author}
              authorUrl={column.author_url}
              version={column.version}
              origin={column.origin}
              metrics={[{ key: column.id, name: column.name }]}
            />
          </div>
        </div>
      </button>

      <div className="flex-none pt-5 pr-5">
        <DocLink measurementId={column.measurement_id} measurementName={column.name} />
      </div>
    </div>
  );
}

/** A multi-column plugin: its name/description/schema shown once, then
 * one independently toggleable row per column it provides. */
function ColumnGroup({ columns, activeIds, onToggle }) {
  const plugin = columns[0]; // name/description/route/schemas identical across every sibling
  return (
    <div className="border-b border-[var(--divider)]">
      <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-2">
        <div className="min-w-0">
          <div className="text-[15px] font-semibold text-[var(--fg)] mb-1">{plugin.name}</div>
          <p className="text-[13px] text-[var(--fg-2)] m-0 leading-relaxed mb-2">{plugin.description}</p>
          <SchemaPreview plugin={plugin} />
          <div className="mt-2">
            <AttributionCard
              author={plugin.author}
              authorUrl={plugin.author_url}
              version={plugin.version}
              origin={plugin.origin}
              metrics={columns.map(c => ({ key: c.id, name: c.column_label }))}
            />
          </div>
        </div>
        <div className="flex-none pt-0.5">
          <DocLink measurementId={plugin.measurement_id} measurementName={plugin.name} />
        </div>
      </div>

      <div className="pb-1">
        {columns.map(column => {
          const active = activeIds.includes(column.id);
          return (
            <button
              key={column.id}
              onClick={() => onToggle(column.id)}
              aria-pressed={active}
              className="flex items-center gap-3 w-full px-5 py-2 text-left cursor-pointer bg-transparent border-none transition-colors duration-150"
              style={{ background: active ? 'var(--accent-soft)' : 'transparent' }}
            >
              <ToggleIndicator active={active} />
              <span className="text-sm text-[var(--fg-1)]">{column.column_label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export const MeasurementPicker = memo(function MeasurementPicker({ manifest, activeIds, onToggle, onClose }) {
  // One entry per plugin's `measurement_id`, each holding every column it
  // provides — manifest order is preserved, so a plugin's group appears
  // where its first column would have.
  const groups = useMemo(() => {
    const byId = new Map();
    for (const column of manifest) {
      if (!byId.has(column.measurement_id)) byId.set(column.measurement_id, []);
      byId.get(column.measurement_id).push(column);
    }
    return [...byId.values()];
  }, [manifest]);

  return (
    <Overlay
      onClose={onClose}
      ariaLabel="Measurements"
      className="fixed inset-0 z-80 flex items-start justify-center pt-[12vh] px-5 pb-5"
      style={{ background: 'color-mix(in oklab, var(--bg-inset) 70%, transparent)', backdropFilter: 'blur(3px)' }}
      contentClassName="w-full max-w-[560px] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] overflow-hidden animate-[corrPop_var(--dur-fast)_var(--ease-out)]"
    >

        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-[var(--divider)]">
          <div>
            <div className="eyebrow mb-1">MEASUREMENTS</div>
            <p className="text-sm text-[var(--fg-2)] m-0">Select which metrics to compute for this ETF</p>
          </div>
          <button onClick={onClose} className="flex-none w-8 h-8 grid place-items-center bg-transparent border border-[var(--border)] rounded-[var(--radius-sm)] text-[var(--fg-2)] cursor-pointer">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
          </button>
        </div>

        {/* Measurement list, grouped by plugin */}
        <div className="corr-scroll max-h-[400px] overflow-y-auto">
          {groups.map(columns => (
            columns.length === 1
              ? <SingleColumnRow key={columns[0].measurement_id} column={columns[0]} active={activeIds.includes(columns[0].id)} onToggle={onToggle} />
              : <ColumnGroup key={columns[0].measurement_id} columns={columns} activeIds={activeIds} onToggle={onToggle} />
          ))}

          {manifest.length === 0 && (
            <div className="p-8 text-center text-sm text-[var(--fg-3)]">
              No measurements available — is the backend running?
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-[var(--divider)] flex items-center justify-between">
          <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-3)]">
            {activeIds.length} of {manifest.length} active
          </span>
          <button
            onClick={onClose}
            className="font-[var(--font-mono)] text-xs font-semibold text-[var(--accent)] bg-[var(--accent-soft)] border border-[var(--accent-ring)] rounded-full px-4 py-1.5 cursor-pointer transition-colors duration-150"
          >
            Done
          </button>
        </div>
    </Overlay>
  );
});
