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
 *
 * `CostBadge` (issue #115) sits beside the origin badge, reading
 * `manifest.cost` — the rating computed once, server-side, at the
 * plugin's own `window_default`, the same value a worked example is
 * always computed against (examples.py never wires a doc to the table's
 * live window control either).
 *
 * `columns` (issue #107) is every manifest row this plugin provides — one
 * for a single-column measurement, several for one declaring `columns`
 * (issue #100; first shipped for real by #107's fund-relation and
 * capture-ratio plugins). `manifest` itself (identity fields: name,
 * description, route, schemas — identical across a plugin's own columns)
 * still drives the header and the doc/worked-example fetch; only "In the
 * table" below needs the full list, since column header, filtering and
 * default-on differ per column.
 */
import { memo } from 'react';
import { DocMdx } from './DocMdx';
import { WorkedExample } from './WorkedExample';
import { AttributionCard } from '../ui/AttributionCard';
import { CostBadge } from '../ui/CostBadge';

export const MeasurementDoc = memo(function MeasurementDoc({ manifest, columns, doc }) {
  const frontmatter = doc?.frontmatter || {};
  const title = frontmatter.title || manifest?.name || doc?.id;
  const summary = frontmatter.summary || manifest?.description;
  const mdx = doc?.mdx || null;
  const placesItsOwnExample = !!mdx && mdx.includes('<WorkedExample');
  const resolvedColumns = columns?.length ? columns : (manifest ? [manifest] : []);

  return (
    <article className="max-w-[760px] w-full">
      <header className="mb-6">
        <div className="flex items-center gap-2.5 mb-2">
          <span className="font-[var(--font-mono)] text-[10px] uppercase tracking-wider text-[var(--fg-2)] bg-[var(--bg-3)] rounded-full px-2.5 py-0.5">
            {doc?.origin === 'addon' ? 'Plugged-in' : 'Official'}
          </span>
          <CostBadge cost={manifest?.cost} />
          {manifest?.id && (
            <span className="font-[var(--font-mono)] text-[11px] text-[var(--fg-3)]">
              {manifest.measurement_id ?? manifest.id}
            </span>
          )}
        </div>
        <h1 className="text-[28px] font-extrabold text-[var(--fg)] tracking-tight m-0">{title}</h1>
        {summary && <p className="text-[15px] leading-relaxed text-[var(--fg-2)] mt-2 mb-0">{summary}</p>}
        {/* Attribution is resolved with the doc's own frontmatter
            already merged over the class (issue #114) - frontmatter,
            the more specific statement about *this documentation*,
            already won by the time it reached `doc`, so this card never
            needs to know the class's own unresolved value. No `origin`
            here: the badge two lines up already says Official/Plugged-in,
            and repeating it in the card would be the same fact twice. */}
        <div className="mt-3">
          <AttributionCard
            author={frontmatter.author}
            authorUrl={frontmatter.author_url}
            version={frontmatter.version}
            metrics={resolvedColumns.map(c => ({
              key: c.id,
              name: c.column_label || c.name,
            }))}
          />
        </div>
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

      {manifest && <ReferencePanels manifest={manifest} columns={resolvedColumns} />}
    </article>
  );
});

// ── Reference panels, derived entirely from the manifest ─────────────────

const ReferencePanels = memo(function ReferencePanels({ manifest, columns }) {
  const multiColumn = columns.length > 1;

  return (
    <>
      <Panel title="In the table">
        {multiColumn ? (
          <div className="flex flex-col gap-4">
            {columns.map(col => (
              <div key={col.id} className="border border-[var(--border)] rounded-[var(--radius-md)] overflow-hidden">
                <div className="px-3 py-2 bg-[var(--bg-2)] border-b border-[var(--border)] font-[var(--font-mono)] text-[12px] font-bold text-[var(--fg)]">
                  {col.column_label}
                </div>
                <Rows
                  rows={[
                    ['Shown by default', col.default_enabled ? 'Yes' : 'No — enable it in Metrics'],
                    ['Sorting', describeSort(col)],
                    ['Filtering', describeFilter(col)],
                  ]}
                  bare
                />
              </div>
            ))}
            <Rows rows={[['Window', describeWindow(manifest)]]} />
          </div>
        ) : (
          <Rows
            rows={[
              ['Column header', manifest.column_label],
              ['Shown by default', manifest.default_enabled ? 'Yes' : 'No — enable it in Metrics'],
              ['Sorting', describeSort(manifest)],
              ['Filtering', describeFilter(manifest)],
              ['Window', describeWindow(manifest)],
            ]}
          />
        )}
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

/** Null for a plugin with no window at all (issue #101) — Rows drops a
 *  null value, so this column simply gets no "Window" row rather than
 *  one saying "N/A". */
function describeWindow(m) {
  if (!m.window_options?.length) return null;
  const options = m.window_options.map(o => o.label).join(', ');
  const defaultLabel = m.window_options.find(o => o.value === m.window_default)?.label ?? m.window_default;
  return `Shared table control, one of ${options} — ${defaultLabel} by default. This page's worked example below uses the default.`;
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

/** `bare` drops the border/radius wrapper for a Rows table nested inside
 *  another bordered box (issue #107's per-column table in ReferencePanels
 *  above) — the parent's own border is enough. */
const Rows = memo(function Rows({ rows, bare = false }) {
  return (
    <div className={bare ? 'corr-scroll overflow-x-auto' : 'corr-scroll overflow-x-auto border border-[var(--border)] rounded-[var(--radius-md)]'}>
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
