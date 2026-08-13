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
 */
import { useState, useEffect } from 'react';
import { evaluate } from '@mdx-js/mdx';
import * as runtime from 'react/jsx-runtime';

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

export function MdxCell({ mdx, loading }) {
  const [Content, setContent] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (loading || mdx == null) return;
    let cancelled = false;
    setFailed(false);
    compileMdx(mdx)
      .then(Comp => { if (!cancelled) setContent(() => Comp); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [mdx, loading]);

  if (loading) return <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg-3)]">…</span>;
  if (mdx === null || mdx === undefined) return <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg-3)]">—</span>;
  if (failed) return <span className="font-[var(--font-mono)] text-[13px] text-[var(--danger)]">err</span>;
  if (!Content) return <span className="font-[var(--font-mono)] text-[13px] text-[var(--fg-3)]">…</span>;

  return <Content components={MDX_COMPONENTS} />;
}
