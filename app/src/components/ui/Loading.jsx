/**
 * Loading — reusable loading placeholder component.
 *
 * Variants:
 *  skeleton — shimmer ghost lines (default). Use for text/list placeholders.
 *  chart    — shimmering filled rectangle. Drop in where an AreaChart will appear.
 *  circle   — spinning ring. Use for inline or button-level states.
 *  bar      — sliding horizontal bar. Use for section/page-level progress.
 *
 * All variants fill their parent's width. Height is controlled via the
 * `height` prop (chart) or implied by line count (skeleton).
 * Pass `className` / `style` for positioning overrides.
 */
import { memo } from 'react';

const SHIMMER = {
  background: 'linear-gradient(90deg, var(--bg-3) 25%, var(--bg-2) 50%, var(--bg-3) 75%)',
  backgroundSize: '400% 100%',
  animation: 'shimmer 1.8s ease-in-out infinite',
};

export const Loading = memo(function Loading({
  variant = 'skeleton',
  lines = 3,
  height = 140,
  className = '',
  style = {},
}) {
  if (variant === 'circle') {
    return (
      <div className={`flex items-center justify-center ${className}`} style={style}>
        <div
          className="rounded-full border-2 border-[var(--border-strong)] border-t-[var(--accent)] animate-spin"
          style={{ width: 28, height: 28 }}
        />
      </div>
    );
  }

  if (variant === 'bar') {
    return (
      <div
        className={`w-full rounded-full overflow-hidden bg-[var(--bg-3)] ${className}`}
        style={{ height: 3, ...style }}
      >
        <div
          style={{
            width: '20%',
            height: '100%',
            background: 'var(--accent)',
            borderRadius: 'inherit',
            animation: 'loadingSlide 1.6s ease-in-out infinite',
          }}
        />
      </div>
    );
  }

  if (variant === 'chart') {
    return (
      <div
        className={`w-full rounded-[var(--radius-md)] ${className}`}
        style={{ height: height + 'px', ...SHIMMER, ...style }}
      />
    );
  }

  // skeleton (default)
  return (
    <div className={`flex flex-col gap-2 w-full ${className}`} style={style}>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="rounded-[var(--radius-sm)]"
          style={{
            height: 13,
            width: i === lines - 1 ? '62%' : '100%',
            ...SHIMMER,
            animationDelay: i * 80 + 'ms',
          }}
        />
      ))}
    </div>
  );
});
