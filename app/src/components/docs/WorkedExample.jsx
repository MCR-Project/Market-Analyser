/**
 * WorkedExample — a measurement's documentation, shown rather than told.
 *
 * Fetches GET /api/measurement-docs/{id}/example and renders three things
 * side by side: the real values each input getter returned, what the
 * measurement computed from them, and the cell that ends up in the table.
 * For value_held that reads as AUM x weight -> $57.2B, with numbers the
 * reader can check against the dashboard.
 *
 * The cells are rendered with MdxCell — the real table vocabulary, not a
 * doc-local imitation. That is deliberate and is the one place a doc
 * tracks MdxCell: the section's whole claim is "this is what you see in
 * the table", so it has to keep being true when the table changes,
 * including a null's reason (issue #99) — a doc page showing a dash
 * ought to explain it the same way the table does.
 *
 * A multi-column plugin (issue #100, first shipped for real by #107's
 * fund-relation and capture-ratio measurements) sends a `columns` array
 * alongside `per_ticker`/`per_ticker_mdx`/`per_ticker_reason`, each keyed
 * one level deeper by column key — the same nesting `run()` itself uses.
 * The result table below grows one "computed value + cell" pair of
 * columns per declared column instead of one flat pair, rather than
 * picking a single column to show and silently dropping the rest.
 *
 * Every number here comes from the backend, which computes over the whole
 * fund and truncates afterwards. When the fetch fails this renders a
 * plain statement that the example is unavailable — never a blank space,
 * and never a fabricated number.
 */
import { Fragment, memo } from 'react';
import { useFetch } from '../../hooks/useFetch';
import { api } from '../../utils/api';
import { MdxCell } from '../ui/MdxCell';
import { Loading } from '../ui/Loading';

/** Render one sampled input value compactly, by shape. */
function InputSample({ sample }) {
  // [[ticker, weight], ...] — the shape holdings comes back as.
  if (Array.isArray(sample) && sample.every(r => Array.isArray(r) && r.length === 2)) {
    return (
      <Rows rows={sample.map(([k, v]) => [k, typeof v === 'number' ? v : String(v)])} />
    );
  }

  if (sample && typeof sample === 'object' && !Array.isArray(sample)) {
    return (
      <div className="flex flex-col gap-3">
        {Object.entries(sample)
          .filter(([, v]) => v !== null && v !== undefined)
          .map(([key, value]) => (
            <div key={key}>
              <div className="font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] mb-1">{key}</div>
              <Value value={value} />
            </div>
          ))}
      </div>
    );
  }

  return <Value value={sample} />;
}

/** One value, rendered by shape rather than dumped as JSON. */
function Value({ value }) {
  // A square, same-keyed nested dict is a matrix — the correlation matrix
  // is exactly this, and flattening it to a line of JSON is the least
  // readable way to show the thing the doc is about.
  const grid = value && typeof value === 'object' && !Array.isArray(value)
    ? asMatrix(value)
    : null;
  if (grid) return <Matrix keys={grid} values={value} />;

  if (value && typeof value === 'object') {
    const entries = Array.isArray(value)
      ? value.map((v, i) => [String(i), v])
      : Object.entries(value);
    const scalar = entries.every(([, v]) => v === null || typeof v !== 'object');
    if (scalar) {
      return <Rows rows={entries.map(([k, v]) => [k, String(v)])} />;
    }
  }

  if (value !== null && typeof value === 'object') {
    return (
      <pre className="corr-scroll overflow-x-auto m-0 text-[12px] font-[var(--font-mono)] text-[var(--fg-1)]">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  return (
    <span className="font-[var(--font-mono)] text-[12px] text-[var(--fg)] break-words">{String(value)}</span>
  );
}

/**
 * Is this a square matrix — every value a dict over the same keys as the
 * outer one? Returns those keys, or null if it isn't.
 */
function asMatrix(sample) {
  const keys = Object.keys(sample);
  if (keys.length < 2) return null;
  const square = keys.every(k => {
    const row = sample[k];
    if (!row || typeof row !== 'object' || Array.isArray(row)) return false;
    const rowKeys = Object.keys(row);
    return rowKeys.length === keys.length && rowKeys.every(rk => keys.includes(rk));
  });
  return square ? keys : null;
}

const Matrix = memo(function Matrix({ keys, values }) {
  return (
    <div className="corr-scroll overflow-x-auto">
      <table className="border-collapse text-[12px] font-[var(--font-mono)]">
        <thead>
          <tr>
            <th className="px-2 py-1" />
            {keys.map(k => (
              <th key={k} className="px-2.5 py-1 text-[10px] text-[var(--fg-2)] font-normal text-right whitespace-nowrap">{k}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map(rowKey => (
            <tr key={rowKey}>
              <td className="px-2 py-1 text-[10px] text-[var(--fg-2)] whitespace-nowrap">{rowKey}</td>
              {keys.map(colKey => {
                const v = values[rowKey][colKey];
                const n = typeof v === 'number' ? v : null;
                return (
                  <td
                    key={colKey}
                    className="px-2.5 py-1 text-right tabular-nums whitespace-nowrap"
                    style={{ color: rowKey === colKey ? 'var(--fg-3)' : 'var(--fg)' }}
                  >
                    {n === null ? String(v) : n.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});

const Rows = memo(function Rows({ rows }) {
  return (
    <div className="corr-scroll overflow-x-auto">
      <table className="w-full border-collapse text-[12.5px]">
        <tbody>
          {rows.map(([key, value]) => (
            <tr key={key}>
              <td className="font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] pr-4 py-1 align-top whitespace-nowrap">{key}</td>
              <td className="font-[var(--font-mono)] text-[12px] text-[var(--fg)] py-1 tabular-nums break-all">
                {typeof value === 'number' ? value : value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});

export const WorkedExample = memo(function WorkedExample({ measurementId }) {
  const { data, loading, error } = useFetch(
    (signal) => api.getMeasurementExample(measurementId, { signal }),
    [measurementId],
    { fallback: null }
  );

  if (loading) {
    return (
      <section className="my-6">
        <SectionHeading>Worked example</SectionHeading>
        <Loading variant="skeleton" lines={5} />
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="my-6">
        <SectionHeading>Worked example</SectionHeading>
        <p className="text-[13px] text-[var(--fg-2)] m-0">
          The live example could not be computed right now, so it is not
          shown — the explanation above still applies.
        </p>
      </section>
    );
  }

  const { etf_id, tickers = [], inputs = [], columns, per_ticker = {}, per_ticker_mdx = {},
          per_ticker_reason = {}, truncated, total_tickers, window_label } = data;
  const multiColumn = Array.isArray(columns) && columns.length > 0;

  return (
    <section className="my-6">
      <SectionHeading>Worked example</SectionHeading>
      <p className="text-[13px] text-[var(--fg-2)] mt-0 mb-4">
        Computed live for <strong className="text-[var(--fg)] font-semibold">{etf_id}</strong>
        {truncated && total_tickers
          ? <> — showing {tickers.length} of its {total_tickers} holdings.</>
          : '.'}
        {/* window_label is absent for a plugin with no window at all
            (issue #101) - present only for the ones where the number
            actually depends on it. */}
        {window_label && (
          <> Over the <strong className="text-[var(--fg)] font-semibold">{window_label}</strong> window
          — the table's own default; change it there and this page keeps showing that one.</>
        )}
      </p>

      {/* ── The inputs it started from ── */}
      {inputs.map(input => (
        <div key={input.name} className="mb-4 border border-[var(--border)] rounded-[var(--radius-md)] overflow-hidden">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5 bg-[var(--bg-2)] border-b border-[var(--border)]">
            <span className="font-[var(--font-mono)] text-[12px] font-bold text-[var(--fg)]">{input.name}</span>
            {Object.entries(input.defaults || {}).map(([k, v]) => (
              <span key={k} className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] bg-[var(--bg-3)] rounded px-1.5 py-0.5">
                {k}={String(v)}
              </span>
            ))}
            {input.truncated && (
              <span className="font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] ml-auto">truncated</span>
            )}
          </div>
          {input.description && (
            <p className="text-[13px] leading-relaxed text-[var(--fg-2)] m-0 px-4 pt-3">{input.description}</p>
          )}
          <div className="px-4 py-3">
            <InputSample sample={input.sample} />
          </div>
        </div>
      ))}

      {/* ── What it computed, and how that lands in the table ── */}
      <div className="border border-[var(--border)] rounded-[var(--radius-md)] overflow-hidden">
        <div className="px-4 py-2.5 bg-[var(--bg-2)] border-b border-[var(--border)]">
          <span className="font-[var(--font-mono)] text-[12px] font-bold text-[var(--fg)]">result</span>
        </div>
        <div className="corr-scroll overflow-x-auto">
          {multiColumn ? (
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  <Th rowSpan={2}>Ticker</Th>
                  {columns.map(col => (
                    <Th key={col.key} colSpan={2}>{col.label}</Th>
                  ))}
                </tr>
                <tr>
                  {columns.map(col => (
                    <Fragment key={col.key}>
                      <Th>Value</Th>
                      <Th>In the table</Th>
                    </Fragment>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tickers.map(ticker => (
                  <tr key={ticker}>
                    <td className="px-4 py-2 border-b border-[var(--divider)] font-[var(--font-mono)] text-[12px] font-bold text-[var(--fg)] whitespace-nowrap">{ticker}</td>
                    {columns.map(col => (
                      <Fragment key={col.key}>
                        <td className="px-4 py-2 border-b border-[var(--divider)] border-l border-l-[var(--divider)] font-[var(--font-mono)] text-[12px] text-[var(--fg-1)] tabular-nums whitespace-nowrap">
                          {(per_ticker[col.key] || {})[ticker] ?? '—'}
                        </td>
                        <td className="px-4 py-2 border-b border-[var(--divider)] min-w-[140px]">
                          <MdxCell
                            mdx={(per_ticker_mdx[col.key] || {})[ticker]}
                            reason={(per_ticker_reason?.[col.key] || {})[ticker]}
                          />
                        </td>
                      </Fragment>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  <Th>Ticker</Th>
                  <Th>Computed value</Th>
                  <Th>As shown in the table</Th>
                </tr>
              </thead>
              <tbody>
                {tickers.map(ticker => (
                  <tr key={ticker}>
                    <td className="px-4 py-2 border-b border-[var(--divider)] font-[var(--font-mono)] text-[12px] font-bold text-[var(--fg)] whitespace-nowrap">{ticker}</td>
                    <td className="px-4 py-2 border-b border-[var(--divider)] font-[var(--font-mono)] text-[12px] text-[var(--fg-1)] tabular-nums whitespace-nowrap">
                      {per_ticker[ticker] ?? '—'}
                    </td>
                    <td className="px-4 py-2 border-b border-[var(--divider)] min-w-[180px]">
                      <MdxCell mdx={per_ticker_mdx[ticker]} reason={per_ticker_reason[ticker]} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </section>
  );
});

function SectionHeading({ children }) {
  return (
    <h2 className="text-[19px] font-bold text-[var(--fg)] tracking-tight mt-8 mb-2.5 pb-1.5 border-b border-[var(--divider)]">
      {children}
    </h2>
  );
}

function Th({ children, ...rest }) {
  return (
    <th
      className="text-left font-[var(--font-mono)] text-[10px] uppercase tracking-wider text-[var(--fg-2)] px-4 py-2 border-b border-[var(--border)] whitespace-nowrap"
      {...rest}
    >
      {children}
    </th>
  );
}
