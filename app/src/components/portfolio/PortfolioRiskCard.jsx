/**
 * PortfolioRiskCard — how independently this basket's own holdings move
 * (issue #113): average pairwise correlation and the effective number of
 * independent bets the basket's own risk contributions add up to.
 *
 * Its own card, its own endpoint (POST /api/portfolio/risk), and its own
 * fetch — deliberately not part of PortfolioSummary.jsx's grid. A
 * correlation matrix over the basket is a second, wider price read than
 * `simulate` needs, so making every run pay for it would slow down every
 * portfolio nobody asked a risk question of; `usePortfolioRisk` only
 * issues the request once a tile here is actually switched on, and
 * settles it independently of `usePortfolioSimulation` so a 503 from this
 * endpoint never touches the run's own chart or its other tiles.
 *
 * Mirrors FundMetricsCard.jsx almost exactly — same registry mechanism
 * (backend/portfolio_metrics/), filtered here to computed_from="risk"
 * instead of "etf_id" — "different metrics, one mechanism" the same way
 * that card already states it.
 */
import { memo } from 'react';

function ratio(value) {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(2)}×`;
}

// A bare Pearson correlation coefficient, -1..1 — not a percentage and
// deliberately not tone-coloured, since a negative reading here is not
// "bad" the way a negative return is: it is the more-diversified end of
// the same number a positive reading is the less-diversified end of.
function correlation(value) {
  if (value === null || value === undefined) return '—';
  return value.toFixed(2);
}

/** `reason` (issue #99's convention) is why this basket's value is a dash
 *  — read off the risk response's own `reasons`, keyed by the same id the
 *  metric registry uses. `title` alone is not reliably announced to a
 *  screen reader, so a `reason` also gets its own `sr-only` text. */
function Stat({ label, value, title, reason }) {
  return (
    <div title={reason || title}>
      <div className="eyebrow mb-1">{label}</div>
      <div className="text-[15px] font-extrabold tabular-nums tracking-tight text-[var(--fg)]">
        {value}
      </div>
      {reason && <span className="sr-only"> — {reason}</span>}
    </div>
  );
}

/** One tile, drawn according to its metric's declared `format` — the
 *  only place in this file that branches on what kind of number a risk
 *  metric is, so adding one whose shape already fits "ratio" or
 *  "correlation" needs no change here at all. */
function MetricTile({ metric, values, reasons }) {
  const value = values[metric.id];
  const reason = reasons[metric.id];
  const label = (metric.tile_label || metric.name).toUpperCase();

  if (metric.format === 'ratio') {
    return <Stat label={label} value={ratio(value)} title={metric.description} reason={reason} />;
  }
  if (metric.format === 'correlation') {
    return <Stat label={label} value={correlation(value)} title={metric.description} reason={reason} />;
  }
  // Any future, unrecognised format falls back to a plain read rather
  // than rendering nothing at all — the same "safest default" rule
  // PortfolioSummary's and FundMetricsCard's own MetricTile follow.
  return (
    <Stat
      label={label}
      value={value === null || value === undefined ? '—' : String(value)}
      title={metric.description}
      reason={reason}
    />
  );
}

export const PortfolioRiskCard = memo(function PortfolioRiskCard({ portfolioRisk, onOpenPicker }) {
  const { tileMetrics, activeIds, values, reasons, loading } = portfolioRisk;

  // Nothing registered at all (backend not reachable yet, or genuinely no
  // computed_from="risk" metrics shipped) — render nothing rather than an
  // empty shell with a Metrics button that opens onto nothing.
  if (tileMetrics.length === 0) return null;

  const activeTiles = tileMetrics.filter(m => activeIds.includes(m.id));

  return (
    <section className="bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] mb-4">
      <div className="flex items-center justify-between px-5 pt-4 pb-0">
        <div className="eyebrow">PORTFOLIO RISK</div>
        <button
          onClick={onOpenPicker}
          className="font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] bg-transparent border border-[var(--border)] rounded-full px-3 py-1 cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-2)] hover:border-[var(--border-strong)]"
        >
          Metrics
        </button>
      </div>

      {activeTiles.length === 0 ? (
        <p className="text-[13px] text-[var(--fg-2)] px-5 pt-2 pb-4 m-0">
          Nothing selected — use Metrics to choose what shows here.
        </p>
      ) : (
        <div
          className="grid grid-cols-2 gap-5 p-5"
          style={{ opacity: loading ? 0.6 : 1, transition: 'opacity 120ms' }}
        >
          {activeTiles.map(metric => (
            <MetricTile key={metric.id} metric={metric} values={values} reasons={reasons} />
          ))}
        </div>
      )}
    </section>
  );
});
