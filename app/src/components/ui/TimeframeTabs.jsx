/**
 * TimeframeTabs — compact 1W / 1M / 1Y / 5Y toggle for chart period selection.
 * Props: active (current tf string), onChange (callback with new tf).
 */
import { memo } from 'react';

const TIMEFRAMES = ['1W', '1M', '1Y', '5Y'];

export const TimeframeTabs = memo(function TimeframeTabs({ active, onChange }) {
  return (
    <div className="inline-flex p-[3px] bg-[var(--bg-3)] rounded-[var(--radius-md)] gap-[1px] flex-none">
      {TIMEFRAMES.map(tf => {
        const isActive = active === tf;
        return (
          <button
            key={tf}
            onClick={() => onChange(tf)}
            className="px-2.5 py-[5px] border-none rounded-[7px] cursor-pointer font-[var(--font-mono)] text-xs transition-all duration-150"
            style={{
              fontWeight: isActive ? 700 : 500,
              background: isActive ? 'var(--bg-1)' : 'transparent',
              color: isActive ? 'var(--fg)' : 'var(--fg-2)',
              boxShadow: isActive ? 'var(--shadow-xs)' : 'none',
            }}
          >
            {tf}
          </button>
        );
      })}
    </div>
  );
});
