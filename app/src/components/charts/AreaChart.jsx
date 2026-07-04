/**
 * AreaChart — SVG sparkline with gradient fill for price series.
 *
 * Colored green (--success) when pct >= 0, red (--danger) when pct < 0.
 * Supports interactive hover with crosshair + dot.
 *
 * Props: data (number[]), pct (number, period return %), hoverIdx, onMouseMove/Leave, gradientId, height (px).
 */
import { memo, useMemo } from 'react';

const W = 360, PAD = 4;

export const AreaChart = memo(function AreaChart({ data, pct = 0, hoverIdx, onMouseMove, onMouseLeave, gradientId = 'g0', height = 140 }) {
  const H = height;
  const color = pct >= 0 ? 'var(--color-success)' : 'var(--color-danger)';

  const { line, area, pts } = useMemo(() => {
    const min = Math.min(...data), max = Math.max(...data);
    const span = (max - min) || 1;
    const vertPad = PAD + 6;
    const pts = data.map((y, i) => [
      PAD + (i / Math.max(1, data.length - 1)) * (W - 2 * PAD),
      vertPad + (1 - (y - min) / span) * (H - 2 * vertPad),
    ]);
    const line = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
    const area = line + ` L${(W - PAD).toFixed(1)} ${H} L${PAD} ${H} Z`;
    return { line, area, pts };
  }, [data, H]);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      width="100%"
      className="block overflow-visible"
      style={{ height: H + 'px' }}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.18} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path d={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      {hoverIdx != null && pts[hoverIdx] ? (
        <>
          <line x1={pts[hoverIdx][0]} y1={PAD} x2={pts[hoverIdx][0]} y2={H - PAD} stroke={color} strokeWidth={1} strokeDasharray="3 2" opacity={0.4} vectorEffect="non-scaling-stroke" />
          <circle cx={pts[hoverIdx][0]} cy={pts[hoverIdx][1]} r={4} fill={color} stroke="var(--bg-1)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
        </>
      ) : (
        <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r={3} fill={color} stroke="var(--bg-1)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      )}
      <rect x={0} y={0} width={W} height={H} fill="transparent" onMouseMove={onMouseMove} onMouseLeave={onMouseLeave} style={{ cursor: 'crosshair' }} />
    </svg>
  );
});
