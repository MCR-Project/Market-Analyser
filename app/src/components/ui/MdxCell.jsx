/**
 * MdxCell — compiles and renders a measurement's per-ticker MDX snippet
 * at runtime.
 *
 * Backend measurements (backend/measurements/*) return real MDX/JSX
 * source per ticker — e.g. `<Bar value={0.35} label="0.35" />` — using a
 * small shared vocabulary of components (MDX_COMPONENTS below). The
 * backend picks WHAT to render and with what data; the visual
 * implementation (colors, layout, animation) lives here, once, so every
 * measurement looks consistent without the frontend branching on a
 * per-measurement `format`.
 *
 * This executes backend-authored JSX as real React components — that's
 * only safe because measurement code is first-party and reviewed like
 * any other backend code, never built from unescaped user/API data.
 *
 * Compiled components are cached by source string, since the same
 * ticker's snippet is usually identical across re-renders.
 *
 * `reason` (optional; issue #99) is a measurement-authored explanation
 * for a null value — same trust boundary as `mdx`, never built from
 * fetched or user text — surfaced as a native tooltip and, separately,
 * as real accessible text for a screen reader, on the dash a null value
 * renders as. Ignored once `mdx` is non-null: a reason only ever
 * accompanies a genuine absence.
 *
 * This vocabulary is explicitly *not* a stable contract, unlike the
 * documentation one in `components/docs/DocMdx.jsx` — see that file's
 * own comment for the contrast. `Spark` (issue #106) is this file's own
 * proof of that: a fourth component, added because `Bar`/`Stat`/`Badge`
 * can each only draw one number, and some of the metrics landing in this
 * table are paths rather than levels — a rolling correlation that
 * climbed toward the fund all year and one that fell away from it
 * average to the same ρ and are opposite findings.
 */
import { useState, useEffect } from 'react';
import { evaluate } from '@mdx-js/mdx';
import * as runtime from 'react/jsx-runtime';

// Spark's internal coordinate space — arbitrary since preserveAspectRatio
// "none" stretches it to whatever width the cell gives it (see Spark's
// own comment below); H is the one dimension that actually matters,
// since it is never stretched.
const SPARK_W = 120;
const SPARK_H = 28;
const SPARK_PAD = 3;

/** Shared visual vocabulary available to every measurement's MDX. */
const MDX_COMPONENTS = {
  /** A -1–1 value as a filled bar (by magnitude) + a pill showing `label`.
   * Negative values render in `--negative` (purple) unless `color` is
   * explicitly overridden, so an inverse correlation reads as visually
   * distinct from a positive one rather than just an empty bar. */
  Bar: ({ value = 0, label, color }) => {
    const resolvedColor = color ?? (value < 0 ? 'var(--negative)' : 'var(--accent)');
    return (
      <div className="flex items-center gap-2.5">
        <div className="flex-1 h-[7px] rounded-full bg-[var(--bg-3)] overflow-hidden">
          <div className="h-full rounded-full" style={{ width: Math.round(Math.min(1, Math.abs(value)) * 100) + '%', background: resolvedColor }} />
        </div>
        <span className="font-[var(--font-mono)] text-[13px] font-bold rounded-full px-2.5 py-0.5" style={{ color: resolvedColor, background: 'color-mix(in oklab, ' + resolvedColor + ' 18%, transparent)' }}>
          {label}
        </span>
      </div>
    );
  },
  /** A bold, tabular-nums stat — the default look for a plain formatted value. */
  Stat: ({ text, color = 'var(--fg)' }) => (
    <span className="text-[15px] font-bold tabular-nums" style={{ color }}>{text}</span>
  ),
  /** A small rounded badge for short categorical text. */
  Badge: ({ text, color = 'var(--fg-2)' }) => (
    <span className="text-xs rounded-full px-2.5 py-0.5" style={{ color, background: 'color-mix(in oklab, ' + color + ' 14%, transparent)' }}>{text}</span>
  ),
  /** A short series drawn as a line — a column showing a *path* rather
   * than a level (issue #106). Two holdings can average the same number
   * while one climbed steadily and the other spiked once and sat flat;
   * Bar (a single magnitude) cannot tell them apart, and a series is
   * exactly what it can't express.
   *
   * `values` is the series itself, in order — never what sorting or
   * filtering reads. Those always compare the column's own `per_ticker`
   * scalar (unaffected by this component entirely), so a measurement
   * rendering `<Spark>` still names a scalar to sort/filter by, the same
   * as `<Bar>`/`<Stat>`/`<Badge>` always have (see backend/measurements/
   * CLAUDE.md's "Spark: a path, not a level" section).
   *
   * `baseline` (default 0) is always included in the drawn vertical
   * range, not just the series' own min/max — a series that never
   * crosses it still shows *how far* it stayed away, rather than being
   * rescaled to fill the cell and losing that distance entirely. The
   * line's color follows the same accent/negative split `<Bar>` uses,
   * decided by the series' last point relative to `baseline` unless
   * `color` overrides it.
   *
   * `label` is a plugin-authored sentence describing the path in words
   * ("up all year, mostly in Q3") — there is nothing legible to put
   * inside a `preserveAspectRatio="none"` SVG this narrow, so it never
   * renders as a glyph inside one. It travels the same way a null cell's
   * `reason` already does elsewhere in this file: a native tooltip via
   * `title` for a mouse, and a real `sr-only` text node for a screen
   * reader, since `title` alone is not reliably announced.
   *
   * A series too short to draw (fewer than two usable points) renders
   * the same plain dash a measurement returns for a null value — the
   * ordinary "nothing to show" case is deciding not to render `<Spark>`
   * at all (see its own doc comment above), this is only the defensive
   * fallback for a malformed one. */
  Spark: ({ values = [], label, baseline = 0, color }) => {
    const usable = values.filter(v => typeof v === 'number' && Number.isFinite(v));
    if (usable.length < 2) {
      return <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg-3)]">—</span>;
    }

    const last = usable[usable.length - 1];
    const resolvedColor = color ?? (last < baseline ? 'var(--negative)' : 'var(--accent)');

    const min = Math.min(...usable, baseline);
    const max = Math.max(...usable, baseline);
    const span = (max - min) || 1;
    const toY = (v) => SPARK_H - SPARK_PAD - ((v - min) / span) * (SPARK_H - 2 * SPARK_PAD);

    const points = usable.map((v, i) => [
      SPARK_PAD + (i / (usable.length - 1)) * (SPARK_W - 2 * SPARK_PAD),
      toY(v),
    ]);
    const line = points.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
    const baselineY = toY(baseline);
    const lastPoint = points[points.length - 1];

    return (
      <div className="w-full" title={label}>
        <svg
          viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
          preserveAspectRatio="none"
          width="100%"
          className="block overflow-visible"
          style={{ height: SPARK_H }}
        >
          <line
            x1={SPARK_PAD} y1={baselineY} x2={SPARK_W - SPARK_PAD} y2={baselineY}
            stroke="var(--border)" strokeWidth={1} strokeDasharray="2 2" vectorEffect="non-scaling-stroke"
          />
          <path d={line} fill="none" stroke={resolvedColor} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          <circle cx={lastPoint[0]} cy={lastPoint[1]} r={2.5} fill={resolvedColor} />
        </svg>
        {label && <span className="sr-only">{label}</span>}
      </div>
    );
  },
};

const compileCache = new Map();

function compileMdx(source) {
  if (!compileCache.has(source)) {
    compileCache.set(
      source,
      evaluate(source, runtime).then(m => m.default).catch(err => {
        compileCache.delete(source); // don't poison the cache with a transient failure
        throw err;
      })
    );
  }
  return compileCache.get(source);
}

export function MdxCell({ mdx, loading, reason }) {
  const [Content, setContent] = useState(null);
  const [failed, setFailed] = useState(false);

  // Clear a stale error as soon as a new snippet arrives, during render
  // rather than inside the effect below — see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [prevMdx, setPrevMdx] = useState(mdx);
  if (mdx !== prevMdx) {
    setPrevMdx(mdx);
    setFailed(false);
  }

  useEffect(() => {
    if (loading || mdx == null) return;
    let cancelled = false;
    compileMdx(mdx)
      .then(Comp => { if (!cancelled) setContent(() => Comp); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [mdx, loading]);

  if (loading) return <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg-3)]">…</span>;
  if (mdx === null || mdx === undefined) {
    // A reason (issue #99) rides along as both a native tooltip (`title`,
    // for a mouse) and real accessible text (an `sr-only` span, for a
    // screen reader — `title` alone is not reliably announced). Without
    // one, this is the same plain dash as before: no empty tooltip, no
    // announcement of "no value" with nothing to say why.
    if (reason) {
      return (
        <span
          className="font-[var(--font-mono)] text-[13px] text-[var(--fg-3)] cursor-help border-b border-dotted border-[var(--fg-3)]"
          title={reason}
        >
          <span aria-hidden="true">—</span>
          <span className="sr-only">No value — {reason}</span>
        </span>
      );
    }
    return <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg-3)]">—</span>;
  }
  if (failed) return <span className="font-[var(--font-mono)] text-[13px] text-[var(--danger)]">err</span>;
  if (!Content) return <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg-3)]">…</span>;

  return <Content components={MDX_COMPONENTS} />;
}
