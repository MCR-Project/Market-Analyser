/**
 * cellColor — maps a correlation value (0–1) to a matrix cell's
 * background/foreground colors, from live API data via the correlation
 * measurement (useLiveCorrelation) — no mock generation happens here.
 *
 * `v == null` means the pair has too little overlapping history to
 * correlate at all (issue #97), not a correlation of zero — it gets a
 * hatched, neutral fill instead of a point on the same accent-intensity
 * scale a genuine 0.00 sits on, so the two are never visually confusable.
 */
export function cellColor(v) {
  if (v == null) {
    return {
      bg: 'repeating-linear-gradient(45deg, var(--bg-2), var(--bg-2) 5px, var(--bg-3) 5px, var(--bg-3) 10px)',
      fg: 'var(--fg-3)',
    };
  }
  const intensity = Math.pow(Math.max(0, v), 1.25);
  const pct = Math.round(intensity * 90) + 6;
  return {
    bg: `color-mix(in oklab, var(--accent) ${pct}%, var(--bg-1))`,
    fg: pct > 52 ? 'var(--accent-fg)' : 'var(--fg)',
  };
}
