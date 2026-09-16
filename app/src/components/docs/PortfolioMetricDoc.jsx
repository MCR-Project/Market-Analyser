/**
 * PortfolioMetricDoc — one portfolio metric's full documentation page
 * body (issue #104).
 *
 * The portfolio-metric counterpart to MeasurementDoc.jsx: same three
 * sources (prose, a manifest-derived reference panel, a live worked
 * example), but the reference panel is entirely different, because a
 * portfolio metric has no column/filter/sort config to describe — it has
 * a family, a formula and a null rule instead.
 */
import { memo } from 'react';
import { DocMdx } from './DocMdx';
import { PortfolioMetricWorkedExample } from './PortfolioMetricWorkedExample';

export const PortfolioMetricDoc = memo(function PortfolioMetricDoc({ manifest, doc, families }) {
  const frontmatter = doc?.frontmatter || {};
  const title = frontmatter.title || manifest?.name || doc?.id;
  const summary = frontmatter.summary || manifest?.description;
  const mdx = doc?.mdx || null;
  const placesItsOwnExample = !!mdx && mdx.includes('<WorkedExample');
  const family = families?.[manifest?.family];

  return (
    <article className="max-w-[760px] w-full">
      <header className="mb-6">
        <div className="flex items-center gap-2.5 mb-2">
          <span className="font-[var(--font-mono)] text-[10px] uppercase tracking-wider text-[var(--fg-2)] bg-[var(--bg-3)] rounded-full px-2.5 py-0.5">
            Portfolio metric
          </span>
          {manifest?.id && (
            <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-3)]">{manifest.id}</span>
          )}
        </div>
        <h1 className="text-[28px] font-extrabold text-[var(--fg)] tracking-tight m-0">{title}</h1>
        {summary && <p className="text-[15px] leading-relaxed text-[var(--fg-2)] mt-2 mb-0">{summary}</p>}
      </header>

      {mdx ? (
        <DocMdx mdx={mdx} measurementId={doc?.id} WorkedExampleComponent={PortfolioMetricWorkedExample} />
      ) : (
        <p className="text-[13px] text-[var(--fg-2)] italic my-4">
          No written documentation for this metric yet. Everything below is
          derived from what it declares about itself.
        </p>
      )}

      {!placesItsOwnExample && <PortfolioMetricWorkedExample measurementId={doc?.id} />}

      {manifest && <ReferencePanel manifest={manifest} family={family} />}
    </article>
  );
});

const ReferencePanel = memo(function ReferencePanel({ manifest, family }) {
  return (
    <section className="my-6">
      <h2 className="text-[19px] font-bold text-[var(--fg)] tracking-tight mt-8 mb-3 pb-1.5 border-b border-[var(--divider)]">
        In the summary
      </h2>
      <Rows
        rows={[
          ['Family', family ? `${family.label} — ${family.note}` : manifest.family],
          ['Shown by default', describeTile(manifest)],
          ['Computed from', describeComputedFrom(manifest.computed_from)],
          ['Formula', manifest.formula],
          ['Null rule', manifest.null_rule],
        ]}
      />
    </section>
  );
});

/** A metric reads its value from one of three places - a completed run,
 *  a fund, or the basket's own risk endpoint (issue #113) - and this is
 *  the one spot that turns `computed_from` into a sentence a reader who
 *  has never seen that field can understand. */
function describeComputedFrom(computedFrom) {
  if (computedFrom === 'etf_id') return 'A fund';
  if (computedFrom === 'risk') return "This basket's own risk endpoint";
  return 'A simulated run';
}

/** "Never a tile" covers two different reasons (issue #113): the
 *  dividend trio is prose under the tile grid instead (#68); riskShare
 *  has nowhere on screen that reads a value per holding today (#113) - a
 *  per-holding breakdown does not fit a single number. Naming the reason
 *  read off `family` rather than hardcoding either keeps this honest for
 *  either kind without this component needing to know which one it is. */
function describeTile(manifest) {
  if (!manifest.tile) {
    return manifest.family === 'dividend'
      ? 'Never a tile — shown as prose instead (see the note below the summary)'
      : 'Never a tile — see "How it reads" above for what this figure means per holding';
  }
  return manifest.default_enabled ? 'Yes' : 'No — enable it from the metrics dialog';
}

const Rows = memo(function Rows({ rows }) {
  return (
    <div className="corr-scroll overflow-x-auto border border-[var(--border)] rounded-[var(--radius-md)]">
      <table className="w-full border-collapse text-[13px]">
        <tbody>
          {rows.filter(([, v]) => v != null && v !== '').map(([key, value]) => (
            <tr key={key}>
              <td className="px-3 py-2 border-b border-[var(--divider)] text-[var(--fg-2)] align-top whitespace-nowrap">{key}</td>
              <td className="px-3 py-2 border-b border-[var(--divider)] text-[var(--fg-1)] align-top">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});
