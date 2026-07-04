/**
 * cellColor — maps a correlation value (0–1) to a matrix cell's
 * background/foreground colors, from live API data via the correlation
 * measurement (useLiveCorrelation) — no mock generation happens here.
 */
export function cellColor(v) {
  const intensity = Math.pow(Math.max(0, v ?? 0), 1.25);
  const pct = Math.round(intensity * 90) + 6;
  return {
    bg: `color-mix(in oklab, var(--accent) ${pct}%, var(--bg-1))`,
    fg: pct > 52 ? 'var(--accent-fg)' : 'var(--fg)',
  };
}
