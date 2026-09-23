/**
 * StockMetricsCard — the stock's own risk/return figures (issue #159),
 * scored by running it as a $100 basket-of-one — the standalone-page
 * reading of Benchmark (`CONTEXT.md`) — over the window this card's own
 * `WindowControls` picks.
 *
 * Same registry PortfolioSummary.jsx and FundMetricsCard.jsx already
 * read (`backend/portfolio_metrics/`), same tile-rendering idea (declared
 * `format` picks how a value is drawn, so a metric whose shape already
 * fits one of the formats below needs no change here to appear
 * correctly) — but its own `Stat`/`MetricTile`/format functions rather
 * than importing either of theirs, the same "same registry, its own
 * presentation" choice FundMetricsCard already made against
 * PortfolioSummary. Sharing would mean either pulling in
 * PortfolioSummary's account-row/dividend-note/depleted-note logic, none
 * of which can ever apply here (this Run never pays in or draws out), or
 * carving those out of a component the portfolio page still depends on
 * exactly as they are.
 *
 * Values come from `metrics`, the already-fetched Run's own response
 * (`usePortfolioSimulation`, called by `StockPage` with a synthetic
 * one-holding portfolio) — there is nothing to fetch a second time here,
 * unlike FundMetricsCard's own per-fund values request.
 */
import { memo } from 'react';
import { WindowControls } from '../portfolio/WindowControls';
import { ErrorState } from '../ui/ErrorState';
import { describeFetchError } from '../../utils/errorCopy';

const CURRENCY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

function percent(value, { signed = false } = {}) {
  if (value === null || value === undefined) return '—';
  const text = `${Math.abs(value).toFixed(1)}%`;
  if (!signed) return text;
  return `${value >= 0 ? '+' : '−'}${text}`;
}

// The same "N.NN×" reading PortfolioSummary and FundMetricsCard already
// use for a dimensionless ratio (Calmar, Sharpe, Sortino).
function ratio(value) {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(2)}×`;
}

function days(value) {
  if (value === null || value === undefined) return '—';
  return `${value}d`;
}

function currencySigned(value) {
  if (value === null || value === undefined) return '—';
  return `${value >= 0 ? '+' : '−'}${CURRENCY.format(Math.abs(value))}`;
}

function tone(value) {
  if (value === null || value === undefined) return 'var(--fg)';
  if (value > 0) return 'var(--success)';
  if (value < 0) return 'var(--danger)';
  return 'var(--fg)';
}

/** `reason` (issue #99) is why this Run's value is a dash — read off
 *  `metrics.reasons`, the same sidecar every other metric consumer here
 *  reads. `title` alone is not reliably announced to a screen reader, so
 *  a reason also gets its own `sr-only` text. */
function Stat({ label, value, tone: statTone, title, reason }) {
  return (
    <div title={reason || title}>
      <div className="eyebrow mb-1">{label}</div>
      <div
        className="text-[15px] font-extrabold tabular-nums tracking-tight"
        style={{ color: statTone || 'var(--fg)' }}
      >
        {value}
      </div>
      {reason && <span className="sr-only"> — {reason}</span>}
    </div>
  );
}

function MetricTile({ metric, metrics }) {
  const value = metrics[metric.id];
  const reason = metrics.reasons?.[metric.id];
  const label = (metric.tile_label || metric.name).toUpperCase();

  if (metric.format === 'drawdown') {
    const drawdown = value || {};
    return (
      <Stat
        label={label}
        value={percent(drawdown.value, { signed: true })}
        tone={drawdown.value < 0 ? 'var(--danger)' : 'var(--fg)'}
        title={
          drawdown.peakDate
            ? `Deepest fall, from ${drawdown.peakDate} to ${drawdown.troughDate}`
            : metric.description
        }
        reason={reason}
      />
    );
  }
  if (metric.format === 'percent_signed') {
    return (
      <Stat label={label} value={percent(value, { signed: true })} tone={tone(value)} title={metric.description} reason={reason} />
    );
  }
  if (metric.format === 'percent') {
    return <Stat label={label} value={percent(value)} title={metric.description} reason={reason} />;
  }
  if (metric.format === 'ratio') {
    return <Stat label={label} value={ratio(value)} title={metric.description} reason={reason} />;
  }
  if (metric.format === 'days') {
    return <Stat label={label} value={days(value)} title={metric.description} reason={reason} />;
  }
  if (metric.format === 'currency_signed') {
    return <Stat label={label} value={currencySigned(value)} tone={tone(value)} title={metric.description} reason={reason} />;
  }
  // "currency" and any future unrecognised format both fall back to a
  // plain currency read, the same safest-default rule PortfolioSummary's
  // own MetricTile follows.
  return (
    <Stat
      label={label}
      value={value === null || value === undefined ? '—' : CURRENCY.format(value)}
      title={metric.description}
      reason={reason}
    />
  );
}

export const StockMetricsCard = memo(function StockMetricsCard({
  windowState,
  metrics,
  resolvedStart,
  resolvedEnd,
  loading,
  stale,
  error,
  onRetry,
  tileMetrics,
  activeIds,
  onOpenPicker,
}) {
  const activeTiles = tileMetrics.filter(m => activeIds.includes(m.id));

  return (
    <section className="bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-sm)] p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="eyebrow">METRICS</div>
        <button
          onClick={onOpenPicker}
          className="font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] bg-transparent border border-[var(--border)] rounded-full px-3 py-1 cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-2)] hover:border-[var(--border-strong)]"
        >
          Metrics
        </button>
      </div>

      <WindowControls
        preset={windowState.preset}
        start={windowState.start}
        end={windowState.end}
        resolvedStart={resolvedStart}
        resolvedEnd={resolvedEnd}
        onSelectPreset={windowState.selectPreset}
        onSetWindow={windowState.setWindow}
        canReset={false}
        onReset={() => {}}
      />

      {error ? (
        <ErrorState {...describeFetchError(error)} onRetry={onRetry} />
      ) : activeTiles.length === 0 ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0">
          Nothing selected — use Metrics to choose what shows here.
        </p>
      ) : (
        <div
          className="grid grid-cols-2 sm:grid-cols-3 gap-5"
          style={{ opacity: loading || stale ? 0.6 : 1, transition: 'opacity 120ms' }}
        >
          {activeTiles.map(metric => (
            <MetricTile key={metric.id} metric={metric} metrics={metrics || {}} />
          ))}
        </div>
      )}
    </section>
  );
});
