/**
 * SectorZone — narrow column in the ETF dashboard card showing sector data.
 *
 * Default state: shows the top sector with a progress bar and share %.
 * Hover state: fades to a ranked list of up to 5 sectors with staggered
 * entrance animations (handled via CSS .sector-zone transitions).
 */
import { memo } from 'react';

export const SectorZone = memo(function SectorZone({ label, tag, name, share, ranking }) {
  return (
    <div className="sector-zone flex-none w-[168px] relative border-r border-[var(--divider)] bg-[var(--bg)] cursor-default">
      {/* Default: top sector */}
      <div className="sector-top absolute inset-0 flex flex-col justify-center p-5 gap-1.5">
        <div className="eyebrow mb-1">{label}</div>
        <div className="text-[28px] font-extrabold text-[var(--fg)] tracking-tight leading-[1.05]">{tag}</div>
        <div className="text-[13px] text-[var(--fg-2)]">{name}</div>
        <div className="flex items-center gap-[9px] mt-2">
          <div className="flex-1 h-1.5 rounded-full bg-[var(--bg-3)] overflow-hidden">
            <div className="h-full bg-[var(--accent)] rounded-full" style={{ width: share + '%' }} />
          </div>
          <span className="font-[var(--font-mono)] text-xs font-semibold text-[var(--accent)] tabular-nums">{share}%</span>
        </div>
        <div className="text-[11px] text-[var(--fg-3)] mt-0.5">of fund weight</div>
      </div>

      {/* Hover: ranked breakdown */}
      <div className="sector-rank absolute inset-0 flex flex-col justify-center px-4 py-[18px] gap-2.5">
        <div className="eyebrow mb-[1px]">SECTOR MIX</div>
        {ranking.map((s, i) => (
          <div key={i} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-1.5">
              <span className="text-[12.5px] font-bold text-[var(--fg)] tracking-tight whitespace-nowrap overflow-hidden text-ellipsis">{s.tag}</span>
              <span className="font-[var(--font-mono)] text-[11px] font-semibold text-[var(--accent)] tabular-nums flex-none">{s.share}</span>
            </div>
            <div className="h-[5px] rounded-full bg-[var(--bg-3)] overflow-hidden">
              <div className="h-full bg-[var(--accent)] rounded-full" style={{ width: s.barWidth + '%' }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});
