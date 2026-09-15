/**
 * MetricsPicker — dialog to toggle which metric tiles are shown
 * (issue #104; generalised for the fund metrics card in issue #105).
 *
 * Mirrors MeasurementPicker.jsx in this same directory, simplified: a
 * portfolio or fund metric never groups several tiles under one plugin
 * the way a multi-column measurement does, so every row is a plain
 * toggle — name, one-line description, a doc link. Grouped here by
 * family, with the group's own label and note read off the manifest's
 * `families` rather than hardcoded, the same "declared data, not layout"
 * decision PortfolioSummary.jsx's own row headers follow.
 *
 * `eyebrow`/`subtitle`/`ariaLabel` default to the portfolio summary's own
 * copy; the fund metrics card (`components/etf/FundMetricsCard.jsx`)
 * passes its own so the dialog reads correctly for whichever registry it
 * is toggling — both are the same `backend/portfolio_metrics/` registry
 * underneath, filtered to a different `computed_from` before this
 * component ever sees the list, so nothing here needs to know which one
 * it is. Living in `components/ui/` rather than `components/portfolio/`
 * (where it started, issue #104) is that shared-ness made visible: the
 * portfolio summary and the ETF dashboard are unrelated features that
 * both need this dialog.
 *
 * Non-tile entries (dividendIncome/dividendYield/incomeUnknownFor) never
 * appear here at all — the caller's own hook (usePortfolioMetrics,
 * useFundMetrics) already filters to tile-eligible entries, since there
 * is nothing to toggle about a note that is always shown.
 */
import { memo, useMemo } from 'react';
import { Overlay } from './Overlay';
import { DocLink } from './DocLink';

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

function MetricRow({ metric, active, onToggle }) {
  return (
    <div
      className="flex items-start border-b border-[var(--divider)] transition-colors duration-150"
      style={{ background: active ? 'var(--accent-soft)' : 'transparent' }}
    >
      {/* The row is a wrapper, not a button: the "?" that opens this
          metric's documentation has to be a sibling of the toggle, since
          an anchor cannot live inside a button. */}
      <button
        onClick={() => onToggle(metric.id)}
        aria-pressed={active}
        className="flex items-start gap-4 flex-1 min-w-0 p-4 pr-2 text-left cursor-pointer bg-transparent border-none"
      >
        <div className="mt-0.5"><ToggleIndicator active={active} /></div>
        <div className="flex-1 min-w-0">
          <div className="text-[14px] font-semibold text-[var(--fg)] mb-1">{metric.name}</div>
          <p className="text-[13px] text-[var(--fg-2)] m-0 leading-relaxed">{metric.description}</p>
        </div>
      </button>

      <div className="flex-none pt-4 pr-4">
        <DocLink measurementId={metric.id} measurementName={metric.name} />
      </div>
    </div>
  );
}

export const MetricsPicker = memo(function MetricsPicker({
  tileMetrics, families, activeIds, onToggle, onClose,
  eyebrow = 'METRICS',
  subtitle = 'Select which tiles to show on the summary',
  ariaLabel = 'Portfolio metrics',
  emptyText = 'No portfolio metrics available — is the backend running?',
}) {
  // Grouped by family, manifest order preserved within each — a family
  // with nothing active still lists every one of its metrics, since the
  // dialog's job is to offer every choice, not just the current one.
  const groups = useMemo(() => {
    const byFamily = new Map();
    for (const metric of tileMetrics) {
      if (!byFamily.has(metric.family)) byFamily.set(metric.family, []);
      byFamily.get(metric.family).push(metric);
    }
    return [...byFamily.entries()];
  }, [tileMetrics]);

  return (
    <Overlay
      onClose={onClose}
      ariaLabel={ariaLabel}
      className="fixed inset-0 z-80 flex items-start justify-center pt-[12vh] px-5 pb-5"
      style={{ background: 'color-mix(in oklab, var(--bg-inset) 70%, transparent)', backdropFilter: 'blur(3px)' }}
      contentClassName="w-full max-w-[560px] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] overflow-hidden animate-[corrPop_var(--dur-fast)_var(--ease-out)]"
    >
      <div className="flex items-center justify-between p-5 border-b border-[var(--divider)]">
        <div>
          <div className="eyebrow mb-1">{eyebrow}</div>
          <p className="text-sm text-[var(--fg-2)] m-0">{subtitle}</p>
        </div>
        <button onClick={onClose} className="flex-none w-8 h-8 grid place-items-center bg-transparent border border-[var(--border)] rounded-[var(--radius-sm)] text-[var(--fg-2)] cursor-pointer">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
        </button>
      </div>

      <div className="corr-scroll max-h-[420px] overflow-y-auto">
        {groups.map(([familyKey, familyMetrics]) => (
          <div key={familyKey}>
            <div className="px-4 pt-4 pb-1 font-[var(--font-mono)] text-[10px] uppercase tracking-wide text-[var(--fg-3)]">
              {families[familyKey]?.label || familyKey}
            </div>
            {familyMetrics.map(metric => (
              <MetricRow
                key={metric.id}
                metric={metric}
                active={activeIds.includes(metric.id)}
                onToggle={onToggle}
              />
            ))}
          </div>
        ))}

        {tileMetrics.length === 0 && (
          <div className="p-8 text-center text-sm text-[var(--fg-3)]">
            {emptyText}
          </div>
        )}
      </div>

      <div className="p-4 border-t border-[var(--divider)] flex items-center justify-between">
        <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-3)]">
          {activeIds.length} of {tileMetrics.length} active
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
