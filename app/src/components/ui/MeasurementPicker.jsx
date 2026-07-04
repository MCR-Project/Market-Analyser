/**
 * MeasurementPicker — dialog to toggle which measurements are displayed.
 *
 * Shows every measurement plugin discovered from the backend manifest.
 * Each row has a toggle switch, the measurement name, description, and
 * its input/output schema as a preview. Active measurements are fetched
 * automatically and their results flow into the dashboard.
 *
 *  ┌─────────────────────────────────────────┐
 *  │ MEASUREMENTS                            │
 *  │ Select which metrics to compute         │
 *  ├─────────────────────────────────────────┤
 *  │ [X] Pairwise Correlation                │
 *  │     Pearson ρ of daily returns...       │
 *  │     Inputs: etf_id, period, threshold   │
 *  │     Outputs: matrix, averages, hub...   │
 *  ├─────────────────────────────────────────┤
 *  │ [ ] % of ETF                            │
 *  │     Weight of each holding...           │
 *  └─────────────────────────────────────────┘
 */
import { memo } from 'react';

export const MeasurementPicker = memo(function MeasurementPicker({ manifest, activeIds, onToggle, onClose }) {
  return (
    <div onClick={onClose} className="fixed inset-0 z-80 flex items-start justify-center pt-[12vh] px-5 pb-5" style={{ background: 'color-mix(in oklab, var(--bg-inset) 70%, transparent)', backdropFilter: 'blur(3px)' }}>
      <div onClick={e => e.stopPropagation()} className="w-full max-w-[560px] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] overflow-hidden animate-[corrPop_var(--dur-fast)_var(--ease-out)]">

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

        {/* Measurement list */}
        <div className="corr-scroll max-h-[400px] overflow-y-auto">
          {manifest.map(m => {
            const active = activeIds.includes(m.id);
            const inputKeys = Object.keys(m.input_schema || {});
            const outputKeys = Object.keys(m.output_schema || {});

            return (
              <button
                key={m.id}
                onClick={() => onToggle(m.id)}
                className="flex items-start gap-4 w-full p-5 text-left cursor-pointer border-b border-[var(--divider)] transition-colors duration-150"
                style={{ background: active ? 'var(--accent-soft)' : 'transparent' }}
              >
                {/* Toggle indicator */}
                <div className="flex-none mt-0.5 w-5 h-5 rounded-[var(--radius-xs)] border-2 grid place-items-center transition-colors duration-150"
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

                {/* Measurement info */}
                <div className="flex-1 min-w-0">
                  <div className="text-[15px] font-semibold text-[var(--fg)] mb-1">{m.name}</div>
                  <p className="text-[13px] text-[var(--fg-2)] m-0 leading-relaxed mb-2">{m.description}</p>

                  {/* Schema preview */}
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
                </div>
              </button>
            );
          })}

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
      </div>
    </div>
  );
});
