/**
 * MeasurementDoc — one measurement's full documentation page body.
 *
 * Combines three sources:
 *   1. The measurement's own prose, written as .mdx and compiled by DocMdx
 *   2. Everything the manifest already declares — schemas, how the column
 *      filters and sorts, the route it registers — rendered as reference
 *      panels rather than the tiny key pills the measurement picker shows
 *   3. A live worked example (see WorkedExample)
 *
 * A measurement that ships no .mdx file still gets a useful page: the
 * panels and the worked example are derived, not written, so the only
 * thing missing is the prose — and that is said plainly rather than left
 * as a blank space.
 *
 * <WorkedExample /> is appended automatically unless the doc placed it
 * itself, so an author gets it for free but can position it deliberately.
 */
import { memo } from 'react';
import { DocMdx } from './DocMdx';
import { WorkedExample } from './WorkedExample';

export const MeasurementDoc = memo(function MeasurementDoc({ manifest, doc }) {
  const frontmatter = doc?.frontmatter || {};
  const title = frontmatter.title || manifest?.name || doc?.id;
  const summary = frontmatter.summary || manifest?.description;
  const mdx = doc?.mdx || null;
  const placesItsOwnExample = !!mdx && mdx.includes('<WorkedExample');

  return (
    <article className="max-w-[760px] w-full">
      <header className="mb-6">
        <div className="flex items-center gap-2.5 mb-2">
          <span className="font-[var(--font-mono)] text-[10px] uppercase tracking-wider text-[var(--fg-2)] bg-[var(--bg-3)] rounded-full px-2.5 py-0.5">
            {doc?.origin === 'addon' ? 'Plugged-in' : 'Official'}
          </span>
          {manifest?.id && (
            <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-3)]">{manifest.id}</span>
          )}
        </div>
        <h1 className="text-[28px] font-extrabold text-[var(--fg)] tracking-tight m-0">{title}</h1>
        {summary && <p className="text-[15px] leading-relaxed text-[var(--fg-2)] mt-2 mb-0">{summary}</p>}
      </header>

      {mdx ? (
        <DocMdx mdx={mdx} measurementId={doc?.id} />
      ) : (
        <p className="text-[13px] text-[var(--fg-2)] italic my-4">
          No written documentation for this measurement yet. Everything
          below is derived from what it declares about itself.
        </p>
      )}

      {!placesItsOwnExample && <WorkedExample measurementId={doc?.id} />}

      {manifest && <ReferencePanels manifest={manifest} />}
    </article>
  );
});

// ── Reference panels, derived entirely from the manifest ─────────────────

const ReferencePanels = memo(function ReferencePanels({ manifest }) {
  return (
    <>
      <Panel title="In the table">
        <Rows
          rows={[
            ['Column header', manifest.column_label],
            ['Shown by default', manifest.default_enabled ? 'Yes' : 'No — enable it in Metrics'],
            ['Sorting', describeSort(manifest)],
            ['Filtering', describeFilter(manifest)],
          ]}
        />
      </Panel>

      <Panel title="Inputs and outputs">
        {manifest.uses_inputs?.length > 0 && (
          <p className="text-[13px] text-[var(--fg-2)] mt-0 mb-3">
            Fetches{' '}
            {manifest.uses_inputs.map((name, i) => (
              <span key={name}>
                {i > 0 && ', '}
                <code className="font-[var(--font-mono)] text-[12px] bg-[var(--bg-3)] text-[var(--fg)] rounded px-1.5 py-0.5">{name}</code>
              </span>
            ))}
            . The worked example above shows what each one returned.
          </p>
        )}
        <SchemaTable label="Input" schema={manifest.input_schema} />
        <SchemaTable label="Output" schema={manifest.output_schema} />
      </Panel>

      <Panel title="API">
        <p className="text-[13px] text-[var(--fg-2)] mt-0 mb-2">
          Registered automatically by the measurement registry:
        </p>
        <pre className="corr-scroll overflow-x-auto m-0 p-3 bg-[var(--bg-2)] border border-[var(--border)] rounded-[var(--radius-md)] text-[12.5px] font-[var(--font-mono)] text-[var(--fg-1)]">
          GET /api{manifest.route}
        </pre>
        {manifest.output_schema && Object.keys(manifest.output_schema).length > 0 && (
          <>
            <p className="text-[13px] text-[var(--fg-2)] mt-3 mb-2">Response shape:</p>
            <pre className="corr-scroll overflow-x-auto m-0 p-3 bg-[var(--bg-2)] border border-[var(--border)] rounded-[var(--radius-md)] text-[12.5px] font-[var(--font-mono)] text-[var(--fg-1)]">
              {sampleResponse(manifest.output_schema)}
            </pre>
          </>
        )}
      </Panel>
    </>
  );
});

function describeSort(m) {
  if (m.sort_type === 'custom' && m.sort_order?.length) {
    return `Custom order: ${m.sort_order.join(' → ')} (descending)`;
  }
  if (m.sort_type === 'alphabetical') return 'Alphabetical, on the raw value';
  return 'Numeric, on the raw value — not the rendered cell';
}

function describeFilter(m) {
  if (!m.filterable) return 'Not filterable';
  if (m.filter_type === 'range') {
    return `Range slider from ${m.filter_min} to ${m.filter_max}, in steps of ${m.filter_step}`;
  }
  if (m.filter_type === 'choices') {
    const labels = (m.filter_options || []).map(o => o.label).join(', ');
    return `Dropdown: ${labels}`;
  }
  if (m.filter_type === 'search') return 'Free-text search';
  return 'Filterable';
}

/** A response shape built from the declared output schema, not invented. */
function sampleResponse(schema) {
  const lines = Object.entries(schema).map(
    ([key, spec]) => `  "${key}": ${spec.type}`
  );
  return `{\n${lines.join(',\n')}\n}`;
}

const SchemaTable = memo(function SchemaTable({ label, schema }) {
  const entries = Object.entries(schema || {});
  if (entries.length === 0) return null;

  return (
    <div className="mb-4 last:mb-0">
      <div className="font-[var(--font-mono)] text-[10px] uppercase tracking-wider text-[var(--fg-3)] mb-1.5">{label}</div>
      <div className="corr-scroll overflow-x-auto border border-[var(--border)] rounded-[var(--radius-md)]">
        <table className="w-full border-collapse text-[13px]">
          <tbody>
            {entries.map(([key, spec]) => (
              <tr key={key}>
                <td className="px-3 py-2 border-b border-[var(--divider)] font-[var(--font-mono)] text-[12px] font-bold text-[var(--fg)] align-top whitespace-nowrap">{key}</td>
                <td className="px-3 py-2 border-b border-[var(--divider)] font-[var(--font-mono)] text-[11.5px] text-[var(--fg-2)] align-top whitespace-nowrap">{spec.type}</td>
                <td className="px-3 py-2 border-b border-[var(--divider)] text-[var(--fg-1)] align-top min-w-[200px]">{spec.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
});

const Panel = memo(function Panel({ title, children }) {
  return (
    <section className="my-6">
      <h2 className="text-[19px] font-bold text-[var(--fg)] tracking-tight mt-8 mb-3 pb-1.5 border-b border-[var(--divider)]">{title}</h2>
      {children}
    </section>
  );
});

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
