/**
 * PortfolioSummary — how the run went, in one line (issue #104: driven
 * from the portfolio metric registry rather than hand-written).
 *
 * Every tile — its label, family, formula, null rule and whether it
 * shows by default — is declared by a backend metric class
 * (backend/portfolio_metrics/), the same self-describing-unit pattern
 * the measurement plugin system already uses for the holdings table.
 * `usePortfolioMetrics` (the manifest + `?metrics=`) decides which tiles
 * are active; this component only groups them by family and draws each
 * one according to its declared `format` — it does not know what CAGR
 * or Max Drawdown mean, only that one is "percent_signed" and the other
 * is "drawdown". Adding a metric to the registry is enough for it to
 * appear here correctly formatted, with no change to this file.
 *
 * The actual figures still come from `metrics` — `POST /api/portfolio/
 * simulate`'s unchanged response (issue #104 does not touch the
 * arithmetic or the response keys) — a metric's `id` is exactly the key
 * this component reads out of it.
 *
 * A number the run could not support comes back null rather than zero — a
 * two-day window has no growth rate and no volatility — and shows as a
 * dash. Zero would be a claim, and the wrong one. When the backend can say
 * why (`metrics.reasons`, issue #99), the dash carries that reason as a
 * tooltip and as real accessible text.
 *
 * **Once money keeps arriving there are two questions, and the summary
 * splits into two rows to stop them being read as one** (#67). The
 * account family's row (today: Paid In, Contributed, Gain, Money-
 * Weighted Return) only ever appears once something was actually
 * contributed — with a single lump sum the two families agree exactly,
 * and printing the second row would imply a distinction that is not
 * there. That gate is the one thing about family visibility this
 * component still decides for itself, rather than the manifest: which
 * families exist and what they are called is declared data, but "the
 * account row is pointless until there is an account to speak of" is a
 * fact about *this run*, not about the registry.
 *
 * **Dividend income is a sentence, not a tile** (#68), unchanged by this
 * issue: `dividendIncome`/`dividendYield`/`incomeUnknownFor` are full
 * registry entries (in the dialog's absence, each still has its own doc
 * page) but declare `tile: false`, so `usePortfolioMetrics` never offers
 * them as toggleable tiles and this component never draws them as ones.
 */
import { memo } from 'react';

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

/**
 * `reason` (issue #99) is why *this* run's value is a dash — read off
 * `metrics.reasons`, keyed by the same id the metric registry uses — and
 * takes over the tooltip from the generic `title` when the two would
 * otherwise compete. `title` alone is not reliably announced to a screen
 * reader, so the reason also gets its own `sr-only` text, the same rule
 * MdxCell follows for a measurement cell's dash.
 */
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

/** One tile, drawn according to its metric's declared `format` — the
 *  only place in this file that branches on what kind of number a
 *  metric is, so adding a metric whose shape already fits one of these
 *  five needs no change here at all. */
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
      <Stat
        label={label}
        value={percent(value, { signed: true })}
        tone={tone(value)}
        title={metric.description}
        reason={reason}
      />
    );
  }
  if (metric.format === 'percent') {
    return <Stat label={label} value={percent(value)} title={metric.description} reason={reason} />;
  }
  if (metric.format === 'currency_signed') {
    return (
      <Stat
        label={label}
        value={currencySigned(value)}
        tone={tone(value)}
        title={metric.description}
        reason={reason}
      />
    );
  }
  // "currency" and any future unrecognised format both fall back to a
  // plain currency read — the safest default for a metric this component
  // does not yet know how to draw specially, rather than rendering
  // nothing at all.
  return (
    <Stat
      label={label}
      value={value === null || value === undefined ? '—' : CURRENCY.format(value)}
      title={metric.description}
      reason={reason}
    />
  );
}

/**
 * Why the returns above are already total returns, and what the income
 * inside them came to. Always shown, including when the answer is
 * nothing — a note that appeared only for payers would leave everyone
 * else wondering whether dividends were counted at all.
 */
function DividendNote({ metrics }) {
  const income = metrics.dividendIncome;
  if (income === null || income === undefined) return null;
  const unknown = metrics.incomeUnknownFor || [];

  return (
    <p className="text-[12px] text-[var(--fg-2)] leading-relaxed m-0 px-5 pb-4 -mt-1">
      <strong className="font-bold text-[var(--fg-1)]">These are total returns.</strong>{' '}
      Prices here are dividend-adjusted, so the figures above already
      include income —{' '}
      {income > 0 ? (
        <>
          <strong className="font-bold text-[var(--fg-1)]">{CURRENCY.format(income)}</strong>{' '}
          of it over this window, {percent(metrics.dividendYield)} of everything
          paid in. It is counted where it was reinvested rather than added on
          top, which would be the same money twice.
        </>
      ) : (
        <>and over this window there was none to include.</>
      )}
      {unknown.length > 0 && (
        <>
          {' '}
          <span className="text-[var(--warning)]">
            {unknown.join(', ')} {unknown.length === 1 ? 'is a fund whose' : 'are funds whose'}{' '}
            dividends are not on record here, so {unknown.length === 1 ? 'its' : 'their'}{' '}
            income is missing from that figure — the value and the return still
            include it.
          </span>
        </>
      )}
    </p>
  );
}

export const PortfolioSummary = memo(function PortfolioSummary({ metrics, stale, portfolioMetrics }) {
  const { tileMetrics, families, activeIds } = portfolioMetrics;
  const funded = (metrics.contributed || 0) > 0;

  const activeTiles = tileMetrics.filter(m => activeIds.includes(m.id));
  const byFamily = (key) => activeTiles.filter(m => m.family === key);

  // Manifest order today is portfolio-family first, then account, then
  // dividend (never a tile) — but grouped explicitly by family here
  // rather than assumed, so a reordered manifest still renders its two
  // rows correctly.
  const portfolioTiles = byFamily('portfolio');
  const accountTiles = byFamily('account');
  const showAccountRow = funded && accountTiles.length > 0;

  return (
    <div
      className="mb-4 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)]"
      style={{ opacity: stale ? 0.6 : 1, transition: 'opacity 120ms' }}
    >
      {portfolioTiles.length > 0 && (
        <>
          {funded && (
            <div className="eyebrow px-5 pt-4 pb-0">
              {(families.portfolio?.label || 'THE PORTFOLIO').toUpperCase()} · {(families.portfolio?.note || '').toUpperCase()}
            </div>
          )}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-5 p-5">
            {portfolioTiles.map(metric => (
              <MetricTile key={metric.id} metric={metric} metrics={metrics} />
            ))}
          </div>
        </>
      )}

      <DividendNote metrics={metrics} />

      {showAccountRow && (
        <>
          <div className="eyebrow px-5 pt-4 pb-0 border-t border-[var(--divider)]">
            {(families.account?.label || 'THE ACCOUNT').toUpperCase()} · {(families.account?.note || '').toUpperCase()}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-5 p-5 pt-4">
            {accountTiles.map(metric => (
              <MetricTile key={metric.id} metric={metric} metrics={metrics} />
            ))}
          </div>
        </>
      )}
    </div>
  );
});
