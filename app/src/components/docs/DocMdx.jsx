/**
 * DocMdx — the documentation MDX vocabulary, and the compiler for it.
 *
 * Backend measurements ship long-form docs as .mdx files next to their
 * own module (see backend/measurements/docs.py). This module defines
 * every tag those docs may use: the prose elements MDX produces on its
 * own (headings, paragraphs, tables, code) plus the handful of custom
 * components below.
 *
 * ── Why this is separate from MdxCell ────────────────────────────────
 * MdxCell.jsx has its own vocabulary — Bar, Stat, Badge — but those are
 * designed for a 110px table cell and will keep changing as the table
 * changes. Documentation is written once and read for years. Doc MDX
 * therefore never references the cell components, and this vocabulary is
 * treated as a stable contract:
 *
 *   ADDING a component here is fine.
 *   CHANGING or REMOVING one breaks every doc already written against it.
 *
 * The one deliberate exception is <WorkedExample />, which renders a
 * measurement's real cells using the real cell vocabulary — the whole
 * point of that section is to show what the table actually shows, so it
 * SHOULD track MdxCell. Prose never does.
 *
 * ── Trust boundary ───────────────────────────────────────────────────
 * Doc MDX is compiled and executed as real JSX in the browser, exactly
 * like MdxCell's snippets. That is only safe because docs are
 * first-party files, reviewed like any other code in this repo. Never
 * build doc content from unescaped user or API data.
 */
import { memo, useMemo, useState, useEffect } from 'react';
import { evaluate } from '@mdx-js/mdx';
import * as runtime from 'react/jsx-runtime';
import remarkGfm from 'remark-gfm';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import { WorkedExample } from './WorkedExample';

/** Flatten MDX children down to plain text (for <Formula> without `tex`). */
function textOf(node) {
  if (node == null || node === false) return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  if (node.props) return textOf(node.props.children);
  return '';
}

/**
 * A typeset formula.
 *
 * Prefer the `tex` prop with a template literal — `tex={String.raw`\rho`}` —
 * so backslashes survive however the MDX is authored. Children are
 * accepted as a convenience for simple expressions.
 *
 * `throwOnError: false` means a malformed expression renders in KaTeX's
 * error styling rather than taking the whole page down with it: one bad
 * formula should cost one formula.
 */
const Formula = memo(function Formula({ tex, children, inline = false }) {
  const source = (tex ?? textOf(children)).trim();
  const html = useMemo(() => {
    try {
      return katex.renderToString(source, {
        displayMode: !inline,
        throwOnError: false,
        output: 'html',
      });
    } catch {
      return null;
    }
  }, [source, inline]);

  if (!source) return null;

  // Falls back to the raw source in a monospace block if KaTeX itself
  // failed — unreadable maths still beats a blank space where the
  // definition of the measurement should be.
  if (html === null) {
    return <pre className="corr-scroll overflow-x-auto text-[13px] font-[var(--font-mono)] text-[var(--fg-1)] bg-[var(--bg-2)] border border-[var(--border)] rounded-[var(--radius-md)] p-3 my-4">{source}</pre>;
  }

  if (inline) {
    return <span className="doc-formula-inline" dangerouslySetInnerHTML={{ __html: html }} />;
  }
  return (
    <div className="corr-scroll overflow-x-auto my-5 py-3 px-4 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-md)]">
      <div dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
});

/** A callout. `tone` picks the colour; the two exported wrappers are the API. */
const Callout = memo(function Callout({ tone, label, children }) {
  return (
    <div
      className="flex gap-3 my-5 p-4 rounded-[var(--radius-md)] border"
      style={{
        background: `color-mix(in oklab, ${tone} 10%, transparent)`,
        borderColor: `color-mix(in oklab, ${tone} 35%, transparent)`,
      }}
    >
      <div className="flex-none font-[var(--font-mono)] text-[10px] font-bold uppercase tracking-wider pt-0.5" style={{ color: tone }}>
        {label}
      </div>
      <div className="flex-1 min-w-0 text-[14px] leading-relaxed text-[var(--fg-1)] [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
        {children}
      </div>
    </div>
  );
});

/** An aside worth reading — context, a gotcha, a definition. */
const Note = memo(function Note({ children }) {
  return <Callout tone="var(--color-info)" label="Note">{children}</Callout>;
});

/** A caveat that changes how the number should be read. */
const Warning = memo(function Warning({ children }) {
  return <Callout tone="var(--color-warning)" label="Careful">{children}</Callout>;
});

// ── Prose ────────────────────────────────────────────────────────────────
// Every element MDX can emit, styled with the app's design tokens so a doc
// matches the rest of the UI in both themes. Wide content (tables, code)
// scrolls inside its own container: the page itself must never scroll
// sideways on a narrow window.

const prose = {
  h1: (p) => <h1 className="text-[26px] font-extrabold text-[var(--fg)] tracking-tight mt-8 mb-3 first:mt-0" {...p} />,
  h2: (p) => <h2 className="text-[19px] font-bold text-[var(--fg)] tracking-tight mt-8 mb-2.5 pb-1.5 border-b border-[var(--divider)]" {...p} />,
  h3: (p) => <h3 className="text-[15px] font-bold text-[var(--fg)] mt-6 mb-2" {...p} />,
  h4: (p) => <h4 className="text-[14px] font-semibold text-[var(--fg-1)] mt-5 mb-1.5" {...p} />,
  p: (p) => <p className="text-[14px] leading-[1.75] text-[var(--fg-1)] my-3.5" {...p} />,
  ul: (p) => <ul className="list-disc pl-6 my-3.5 flex flex-col gap-1.5 text-[14px] leading-[1.7] text-[var(--fg-1)]" {...p} />,
  ol: (p) => <ol className="list-decimal pl-6 my-3.5 flex flex-col gap-1.5 text-[14px] leading-[1.7] text-[var(--fg-1)]" {...p} />,
  li: (p) => <li className="pl-1" {...p} />,
  strong: (p) => <strong className="font-bold text-[var(--fg)]" {...p} />,
  em: (p) => <em className="italic" {...p} />,
  hr: () => <hr className="border-0 border-t border-[var(--divider)] my-7" />,
  a: (p) => <a className="text-[var(--accent)] underline underline-offset-2 hover:opacity-80" {...p} />,
  blockquote: (p) => (
    <blockquote className="my-5 pl-4 border-l-2 border-[var(--accent-ring)] text-[var(--fg-2)] italic [&>*:first-child]:mt-0 [&>*:last-child]:mb-0" {...p} />
  ),
  code: (p) => (
    <code className="font-[var(--font-mono)] text-[12.5px] bg-[var(--bg-3)] text-[var(--fg)] rounded-[var(--radius-xs)] px-1.5 py-0.5" {...p} />
  ),
  // A fenced block arrives as <pre><code>. Reset the inline pill styling
  // the nested <code> would otherwise inherit.
  pre: (p) => (
    <pre
      className="corr-scroll overflow-x-auto my-5 p-4 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-md)] text-[12.5px] leading-relaxed font-[var(--font-mono)] text-[var(--fg-1)] [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-inherit"
      {...p}
    />
  ),
  table: (p) => (
    <div className="corr-scroll overflow-x-auto my-5 border border-[var(--border)] rounded-[var(--radius-md)]">
      <table className="w-full border-collapse text-[13px]" {...p} />
    </div>
  ),
  thead: (p) => <thead className="bg-[var(--bg-2)]" {...p} />,
  th: (p) => (
    <th className="text-left font-[var(--font-mono)] text-[10px] uppercase tracking-wider text-[var(--fg-2)] px-3 py-2 border-b border-[var(--border)] whitespace-nowrap" {...p} />
  ),
  td: (p) => <td className="px-3 py-2 border-b border-[var(--divider)] text-[var(--fg-1)] align-top" {...p} />,
};

/**
 * Build the component map handed to a compiled doc.
 *
 * `measurementId` is closed over so <WorkedExample /> knows which
 * measurement to fetch without the doc author having to repeat it.
 * `WorkedExampleComponent` (issue #104) lets a doc from a different
 * registry - a portfolio metric's, which has no per-ticker table to
 * sample and fetches a differently-shaped worked example - supply its own
 * implementation of the same `<WorkedExample />` tag rather than forking
 * the whole vocabulary; every other tag, and the doc author's experience
 * of writing one, stays identical either way.
 */
function createDocComponents(measurementId, WorkedExampleComponent) {
  return {
    ...prose,
    Note,
    Warning,
    Formula,
    WorkedExample: (props) => <WorkedExampleComponent measurementId={measurementId} {...props} />,
  };
}

const compileCache = new Map();

// GitHub-flavoured markdown, for the pipe tables docs lean on to compare
// values side by side. Plain MDX doesn't parse those — without this the
// table styling above is never reached and a table renders as a row of
// literal pipes.
const REMARK_PLUGINS = [remarkGfm];

function compileMdx(source) {
  if (!compileCache.has(source)) {
    compileCache.set(
      source,
      evaluate(source, { ...runtime, remarkPlugins: REMARK_PLUGINS }).then(m => m.default).catch(err => {
        compileCache.delete(source); // don't poison the cache with a transient failure
        throw err;
      })
    );
  }
  return compileCache.get(source);
}

export function DocMdx({ mdx, measurementId, WorkedExampleComponent = WorkedExample }) {
  const [Content, setContent] = useState(null);
  const [failed, setFailed] = useState(false);

  // Clear a stale error/document as soon as a new source arrives, during
  // render rather than in the effect — otherwise the previous doc paints
  // for a frame under the new doc's heading. See
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [prevMdx, setPrevMdx] = useState(mdx);
  if (mdx !== prevMdx) {
    setPrevMdx(mdx);
    setFailed(false);
    setContent(null);
  }

  const components = useMemo(
    () => createDocComponents(measurementId, WorkedExampleComponent),
    [measurementId, WorkedExampleComponent]
  );

  useEffect(() => {
    if (!mdx) return;
    let cancelled = false;
    compileMdx(mdx)
      .then(Comp => { if (!cancelled) setContent(() => Comp); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [mdx]);

  if (!mdx) return null;

  // A doc that won't compile is a first-party authoring mistake. Say so
  // plainly instead of rendering nothing, so it gets noticed and fixed.
  if (failed) {
    return (
      <p className="text-[13px] text-[var(--danger)] my-4">
        This measurement's documentation could not be rendered — its .mdx
        file has a syntax error.
      </p>
    );
  }

  if (!Content) return null;

  return <Content components={components} />;
}
