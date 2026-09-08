/**
 * BrushOverlay — the part of the chart being selected, while it is being
 * selected.
 *
 * Two pieces: the SVG shading, which has to live inside the plot and be
 * drawn in its stretched coordinate space, and the HTML label, which
 * must not be — the plot is scaled horizontally to its container, so any
 * text inside it would be stretched with it.
 *
 * A selection too short to use is shaded in the warning colour instead of
 * the accent. Refusing on release without having said anything on the way
 * down would read as the drag having failed to register.
 */
import { memo } from 'react';

export const BrushShading = memo(function BrushShading({ selection, width, height }) {
  if (!selection) return null;
  const x1 = selection.from * width;
  const x2 = selection.to * width;
  const tone = selection.usable ? 'var(--accent)' : 'var(--warning)';

  return (
    <g aria-hidden="true">
      <rect x={x1} y={0} width={Math.max(x2 - x1, 0.5)} height={height} fill={tone} fillOpacity={0.16} />
      {[x1, x2].map((x, i) => (
        <line
          key={i}
          x1={x} x2={x} y1={0} y2={height}
          stroke={tone} strokeWidth={1} vectorEffect="non-scaling-stroke"
        />
      ))}
    </g>
  );
});

export const BrushLabel = memo(function BrushLabel({ selection }) {
  if (!selection) return null;

  return (
    <div
      className="absolute top-4 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-[var(--radius-md)] border pointer-events-none z-30 whitespace-nowrap"
      style={{
        background: 'var(--bg-1)',
        borderColor: selection.usable ? 'var(--accent-ring)' : 'var(--warning-ring)',
      }}
    >
      <span className="font-[var(--font-mono)] text-[11.5px] text-[var(--fg)]">
        {selection.start} <span aria-hidden="true">→</span> {selection.end}
      </span>
      {!selection.usable && (
        <span className="text-[11.5px] text-[var(--warning)] ml-2">too short</span>
      )}
    </div>
  );
});
