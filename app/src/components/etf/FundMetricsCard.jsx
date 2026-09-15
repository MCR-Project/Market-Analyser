/**
 * FundMetricsCard — fund-level metrics: properties of the whole basket
 * rather than of any one holding (issue #105), in their own card under
 * EtfDashboard.
 *
 * Issue #105's own decision: the identity card's `NET ASSETS / HOLDINGS /
 * AVG ρ` row is already tight, sits inside the fund-picker button's zone,
 * and gets cramped past four or five stats — AVG ρ stays there rather
 * than moving, which would make a familiar card unfamiliar for no gain.
 * This card is a second, independent home for figures that describe the
 * fund as a whole (diversification ratio, variance concentration,
 * tracked weight coverage) rather than any single holding.
 *
 * Driven from the same registry mechanism PortfolioSummary.jsx uses for
 * the portfolio simulator's tiles (`backend/portfolio_metrics/`),
 * filtered by `useFundMetrics` to the `computed_from="etf_id"` entries —
 * a metric declared with a format this component already knows needs no
 * change here to appear, the same promise the portfolio card makes.
 * `MetricsPicker` (in `components/ui/`) is the shared enable/disable
 * dialog both cards use.
 */
import { memo } from 'react';

function ratio(value) {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(2)}×`;
}

function percent(value) {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(1)}%`;
}

/**
 * `reason` (issue #99's convention, carried over from PortfolioSummary's
 * own Stat) is why *this fund's* value is a dash — read off the fund
 * metrics response's own `reasons`, keyed by the same id the metric
 * registry uses. `title` alone is not reliably announced to a screen
 * reader, so a `reason` also gets its own `sr-only` text.
 */
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
 *  only place in this file that branches on what kind of number a fund
 *  metric is, so adding one whose shape already fits "ratio" or
 *  "percent" needs no change here at all. */
function MetricTile({ metric, values, reasons }) {
  const value = values[metric.id];
  const reason = reasons[metric.id];
  const label = (metric.tile_label || metric.name).toUpperCase();

  if (metric.format === 'ratio') {
    return <Stat label={label} value={ratio(value)} title={metric.description} reason={reason} />;
  }
  if (metric.format === 'percent') {
    return <Stat label={label} value={percent(value)} title={metric.description} reason={reason} />;
  }
  // Any future, unrecognised format falls back to a plain read rather
  // than rendering nothing at all — the same "safest default" rule
  // PortfolioSummary's own MetricTile follows.
  return (
    <Stat
      label={label}
      value={value === null || value === undefined ? '—' : String(value)}
      title={metric.description}
      reason={reason}
    />
  );
}

export const FundMetricsCard = memo(function FundMetricsCard({ fundMetrics, onOpenPicker }) {
  const { tileMetrics, activeIds, values, reasons, loading } = fundMetrics;

  // Nothing registered at all (backend not reachable yet, or genuinely
  // no computed_from="etf_id" metrics shipped) — render nothing rather
  // than an empty shell with a Metrics button that opens onto nothing.
  if (tileMetrics.length === 0) return null;

  const activeTiles = tileMetrics.filter(m => activeIds.includes(m.id));

  return (
    <section className="flex-none bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] mb-5 animate-[corrFadeUp_var(--dur-base)_var(--ease-out)]">
      <div className="flex items-center justify-between px-5 pt-4 pb-0">
        <div className="eyebrow">FUND METRICS</div>
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
          className="grid grid-cols-2 sm:grid-cols-3 gap-5 p-5"
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
