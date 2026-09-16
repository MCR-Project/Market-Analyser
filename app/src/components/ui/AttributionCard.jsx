/**
 * AttributionCard — who wrote a plugin, where to read more about them,
 * what version it is, and which metrics it provides (issue #114).
 *
 * Shared by both registries and both places attribution is shown: the
 * measurement picker and the fund/portfolio metrics dialogs (all three
 * built on `MetricsPicker`/`MeasurementPicker`, one row or group per
 * plugin), and the head of a doc page (`MeasurementDoc`/
 * `PortfolioMetricDoc`). It renders from a plain `{author, authorUrl,
 * version, origin, metrics}` shape rather than a measurement or a
 * portfolio-metric object specifically, so the same component serves
 * both registries without a variant — "different metrics, one
 * mechanism" (issue #105's own phrase) applies here too.
 *
 * **An unattributed plugin says so outright.** Crediting the repository
 * owner for a plugin that never declared an author would be the same
 * class of mistake as defaulting a null figure to zero (backend/
 * CLAUDE.md's invariant 7) — so `author` absent renders "Unattributed",
 * never a name nobody actually wrote.
 *
 * `metrics` is every column/metric this one plugin provides — a
 * single-column measurement's or a portfolio metric's own array of one,
 * or several for a multi-column measurement (issue #100). The list is
 * only rendered past one entry: the immediate context (the row's own
 * name, the doc page's own title) already names a lone metric, so
 * repeating it here would be noise, not information — but a reader
 * looking at a two-column plugin's card genuinely learns something
 * finding out both columns come from the one file.
 */
import { memo } from 'react';

const ORIGIN_LABELS = {
  official: 'Official',
  addon: 'Plugged-in',
  portfolio: 'Portfolio metric',
};

export const AttributionCard = memo(function AttributionCard({
  author, authorUrl, version, origin, metrics = [],
}) {
  const originLabel = ORIGIN_LABELS[origin] || origin || null;

  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11.5px] leading-relaxed">
      {originLabel && (
        <span className="flex-none font-[var(--font-mono)] text-[9px] uppercase tracking-wider text-[var(--fg-2)] bg-[var(--bg-3)] rounded-full px-2 py-0.5">
          {originLabel}
        </span>
      )}
      {author ? (
        authorUrl ? (
          <a
            href={authorUrl}
            target="_blank"
            rel="noreferrer"
            onClick={e => e.stopPropagation()}
            className="font-semibold text-[var(--accent)] no-underline hover:underline"
          >
            {author}
          </a>
        ) : (
          <span className="font-semibold text-[var(--fg-1)]">{author}</span>
        )
      ) : (
        <span className="italic text-[var(--fg-3)]">Unattributed</span>
      )}
      {version && (
        <span className="font-[var(--font-mono)] text-[var(--fg-3)]">v{version}</span>
      )}
      {metrics.length > 1 && (
        <span className="text-[var(--fg-3)] basis-full sm:basis-auto">
          Provides {metrics.length}:{' '}
          {metrics.map((m, i) => (
            <span key={m.key}>
              {i > 0 && ', '}
              <span className="text-[var(--fg-2)]">{m.name}</span>
            </span>
          ))}
        </span>
      )}
    </div>
  );
});
