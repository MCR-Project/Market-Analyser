/**
 * SegmentedControl — a small labelled either/or toggle, styled like
 * TimeframeTabs. Props: label (the word beside it), options
 * ([{ value, label }]), value, onChange (called with the new value).
 * Each button reports its state with `aria-pressed`.
 */
import { memo } from 'react';

export const SegmentedControl = memo(function SegmentedControl({ label, options, value, onChange }) {
  return (
    <div className="flex items-center gap-2 flex-none">
      <span className="font-[var(--font-mono)] text-xs text-[var(--fg-2)]">{label}</span>
      <div role="group" aria-label={label} className="inline-flex p-[3px] bg-[var(--bg-3)] rounded-[var(--radius-md)] gap-[1px]">
        {options.map(opt => {
          const isActive = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              aria-pressed={isActive}
              onClick={() => onChange(opt.value)}
              className="px-2.5 py-[5px] border-none rounded-[7px] cursor-pointer font-[var(--font-mono)] text-xs transition-all duration-150"
              style={{
                fontWeight: isActive ? 700 : 500,
                background: isActive ? 'var(--bg-1)' : 'transparent',
                color: isActive ? 'var(--fg)' : 'var(--fg-2)',
                boxShadow: isActive ? 'var(--shadow-xs)' : 'none',
              }}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
});
