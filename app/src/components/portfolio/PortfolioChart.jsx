/**
 * PortfolioChart — what each holding was worth, all the way along.
 *
 * A stacked area: one band per holding, cash when there is any, summing
 * to the portfolio's total at every date. The shape is the point. Under
 * buy and hold the bands drift apart as a winner takes over — the thing a
 * line of total value cannot show and a rebalanced run does not do — so
 * the same portfolio looks visibly different depending on how it is run.
 *
 * Four decisions worth knowing about:
 *
 *  - **Colour follows the ticker, not the ranking.** Bands are stacked
 *    largest-first so the shape reads from the bottom up, but that order
 *    changes with the window; a colour that changed with it would make
 *    two windows of the same portfolio look like two portfolios.
 *
 *  - **Small holdings are grouped, not dropped.** Past a dozen bands the
 *    thin ones are unreadable and unclickable, so the smallest become one
 *    "Other" band that still carries their value. Nothing leaves the
 *    stack, because then it would not add up.
 *
 *  - **No text inside the SVG.** The chart stretches horizontally to its
 *    container (preserveAspectRatio="none"), which would distort any
 *    glyph drawn in it, so every label is HTML positioned over the top.
 *
 *  - **Money paid in is a line, not a band** (#67). A portfolio funded
 *    monthly climbs whether or not anything went up, and a stack alone
 *    cannot say which of the two happened. The paid-in line is drawn over
 *    the bands as a staircase — flat between contributions, stepping on
 *    each one — so the gap between it and the top of the stack is the
 *    gain, readable at a glance and at every date rather than only at the
 *    end. It is absent when there is nothing to say: with a single lump
 *    sum it would be a horizontal rule across the chart.
 *
 * The geometry matches useChartHover's own constants, which is what makes
 * the crosshair land on the date the tooltip is describing.
 */
import { memo, useCallback, useMemo } from 'react';
import { useChartBrush } from '../../hooks/useChartBrush';
import { useChartHover } from '../../hooks/useChartHover';
import { BrushLabel, BrushShading } from '../charts/BrushOverlay';

/** Shared with useChartHover — the hover maths reads these exact numbers,
 *  so the crosshair and the bands cannot disagree about where a date is. */
const W = 360;
const PAD = 4;
const H = 240;

/** Beyond this many bands the thin ones are noise; the smallest are
 *  gathered into one. */
const MAX_BANDS = 10;

/** Chosen for hue separation rather than prettiness, and checked against
 *  both themes: these sit on --bg-1 in light and dark alike. Cash is
 *  deliberately not in here — it is not a holding and reads as neutral. */
const PALETTE = [
  '#7849ff', '#2a8aff', '#2bd47d', '#ffb547', '#ff4d6d',
  '#00c2c7', '#b06bff', '#5b8def', '#f28cb1', '#8bd450',
  '#ff8a3d', '#4ea2ff',
];
const CASH_COLOR = 'var(--fg-3)';
const OTHER_COLOR = 'var(--fg-2)';
// Deliberately not from the palette: money paid in is not a holding, and
// a line the same colour as a band would read as one.
const INVESTED_COLOR = 'var(--fg-1)';

const CURRENCY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

/** Stable across renders and across windows: a key's colour depends only
 *  on the sorted set of keys it belongs to. */
function colorMap(keys) {
  const sorted = [...keys].sort();
  return new Map(sorted.map((key, i) => [key, PALETTE[i % PALETTE.length]]));
}

/**
 * Turn a run into bands: one per holding (or per sector), cash if there
 * is any, and an "Other" band once there are too many to read.
 */
function buildBands(simulation, groupBy, sectorOf) {
  const dates = simulation.dates;
  const blank = () => new Array(dates.length).fill(0);

  const byKey = new Map();
  for (const holding of simulation.holdings) {
    const key = groupBy === 'sector'
      ? (sectorOf?.get(holding.ticker) || 'UNKNOWN')
      : holding.ticker;
    const values = byKey.get(key) || blank();
    for (let i = 0; i < dates.length; i += 1) values[i] += holding.values[i];
    byKey.set(key, values);
  }

  let bands = [...byKey.entries()]
    .map(([key, values]) => ({ key, values, final: values[values.length - 1] }))
    .sort((a, b) => b.final - a.final);

  // Everything past the readable count becomes one band, keeping its
  // value in the stack rather than vanishing out of the total.
  if (bands.length > MAX_BANDS) {
    const kept = bands.slice(0, MAX_BANDS - 1);
    const rest = bands.slice(MAX_BANDS - 1);
    const merged = blank();
    for (const band of rest) {
      for (let i = 0; i < dates.length; i += 1) merged[i] += band.values[i];
    }
    bands = [
      ...kept,
      {
        key: `Other (${rest.length})`,
        values: merged,
        final: merged[merged.length - 1],
        muted: OTHER_COLOR,
      },
    ];
  }

  if (simulation.cash.some(value => value > 0)) {
    bands.push({
      key: 'Cash',
      values: simulation.cash,
      final: simulation.cash[simulation.cash.length - 1],
      muted: CASH_COLOR,
    });
  }

  const colors = colorMap(bands.filter(b => !b.muted).map(b => b.key));
  return bands.map(band => ({ ...band, color: band.muted || colors.get(band.key) }));
}

export const PortfolioChart = memo(function PortfolioChart({
  simulation,
  groupBy,
  onGroupByChange,
  sectorOf,
  sectorsReady,
  stale,
  onSelectWindow,
}) {
  const bands = useMemo(
    () => buildBands(simulation, groupBy, sectorOf),
    [simulation, groupBy, sectorOf]
  );

  const { hoverIdx, onMouseMove, onMouseLeave, tooltip } = useChartHover(
    simulation.total,
    null,
    simulation.dates
  );

  // Bands are positioned by row, so a position across the plot resolves
  // to a row - the same arithmetic the hover uses, from the same
  // constants.
  const resolve = useCallback((fraction) => {
    const dates = simulation.dates;
    if (dates.length === 0) return null;
    const index = Math.round(
      Math.max(0, Math.min(1, (fraction * W - PAD) / (W - 2 * PAD))) * (dates.length - 1)
    );
    return { index, date: dates[index] };
  }, [simulation.dates]);

  const brush = useChartBrush({ resolve, onSelect: onSelectWindow || (() => {}) });

  // Only worth drawing once money has arrived more than once: with a
  // single lump sum the line is a horizontal rule saying nothing.
  const invested = simulation.invested;
  const showInvested = !!invested && invested[invested.length - 1] > invested[0];

  const { paths, ceiling, investedPath } = useMemo(() => {
    const dates = simulation.dates;
    // The paid-in line is inside the plot too - a portfolio worth less
    // than was put into it would otherwise draw it off the top edge.
    const ceiling = Math.max(
      ...simulation.total,
      ...(showInvested ? invested : []),
      1
    );
    const x = i => PAD + (i / Math.max(1, dates.length - 1)) * (W - 2 * PAD);
    const y = value => H - (value / ceiling) * H;

    // Drawn bottom-up: each band's top edge is the running sum, and its
    // bottom edge is the one below it, so the areas meet exactly and the
    // stack is the total by construction.
    const running = new Array(dates.length).fill(0);
    const paths = bands.map(band => {
      const lower = [...running];
      for (let i = 0; i < dates.length; i += 1) running[i] += band.values[i];
      const top = running.map((value, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)} ${y(value).toFixed(2)}`).join(' ');
      const bottom = lower
        .map((value, i) => `L${x(dates.length - 1 - i).toFixed(2)} ${y(lower[dates.length - 1 - i]).toFixed(2)}`)
        .join(' ');
      return { ...band, d: `${top} ${bottom} Z` };
    });

    // A staircase rather than a slope: the money did not arrive gradually
    // between two contributions, it arrived on one date and sat there.
    let investedPath = null;
    if (showInvested) {
      const points = [`M${x(0).toFixed(2)} ${y(invested[0]).toFixed(2)}`];
      for (let i = 1; i < dates.length; i += 1) {
        if (invested[i] !== invested[i - 1]) {
          points.push(`L${x(i).toFixed(2)} ${y(invested[i - 1]).toFixed(2)}`);
        }
        points.push(`L${x(i).toFixed(2)} ${y(invested[i]).toFixed(2)}`);
      }
      investedPath = points.join(' ');
    }

    return { paths, ceiling, investedPath };
  }, [bands, simulation, invested, showInvested]);

  const at = hoverIdx ?? simulation.dates.length - 1;
  const totalAt = simulation.total[at];

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
        <div className="eyebrow">VALUE BY {groupBy === 'sector' ? 'SECTOR' : 'HOLDING'}</div>
        <div className="inline-flex p-[3px] bg-[var(--bg-3)] rounded-[var(--radius-md)] gap-[1px]">
          {[
            { key: 'holding', label: 'By stock' },
            { key: 'sector', label: 'By sector' },
          ].map(option => {
            const active = groupBy === option.key;
            return (
              <button
                key={option.key}
                onClick={() => onGroupByChange(option.key)}
                aria-pressed={active}
                className="px-2.5 py-[5px] border-none rounded-[7px] cursor-pointer text-[12px] transition-all duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                style={{
                  fontWeight: active ? 700 : 500,
                  background: active ? 'var(--bg-1)' : 'transparent',
                  color: active ? 'var(--fg)' : 'var(--fg-2)',
                  boxShadow: active ? 'var(--shadow-xs)' : 'none',
                }}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      </div>

      {groupBy === 'sector' && !sectorsReady && (
        <p className="text-[12px] text-[var(--fg-2)] m-0 mb-2">Loading sectors…</p>
      )}

      <div
        className="relative bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] p-4 pl-14"
        style={{ opacity: stale ? 0.6 : 1, transition: 'opacity 120ms' }}
      >
        {/* Value axis, in HTML so it is not stretched with the chart. */}
        {[1, 0.5, 0].map(fraction => (
          <span
            key={fraction}
            className="absolute left-2 font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] -translate-y-1/2"
            // The SVG stretches horizontally but is exactly H pixels
            // tall, so a value's height in the box is its height on
            // screen, plus the container's own padding.
            style={{ top: `calc(1rem + ${(1 - fraction) * H}px)` }}
          >
            {CURRENCY.format(ceiling * fraction)}
          </span>
        ))}

        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          width="100%"
          className="block"
          style={{ height: `${H}px` }}
          role="img"
          aria-label={`Value of each ${groupBy === 'sector' ? 'sector' : 'holding'} over time, stacked`}
        >
          {[0.25, 0.5, 0.75].map(fraction => (
            <line
              key={fraction}
              x1={0} x2={W}
              y1={H * fraction} y2={H * fraction}
              stroke="var(--divider)"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
          ))}

          {paths.map(band => (
            <path
              key={band.key}
              d={band.d}
              fill={band.color}
              fillOpacity={0.85}
              stroke={band.color}
              strokeWidth={0.5}
              vectorEffect="non-scaling-stroke"
            />
          ))}

          {investedPath && (
            <path
              d={investedPath}
              fill="none"
              stroke={INVESTED_COLOR}
              strokeWidth={1.5}
              strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke"
            />
          )}

          <BrushShading selection={brush.selection} width={W} height={H} />

          {hoverIdx != null && !brush.active && (
            <line
              x1={PAD + (hoverIdx / Math.max(1, simulation.dates.length - 1)) * (W - 2 * PAD)}
              x2={PAD + (hoverIdx / Math.max(1, simulation.dates.length - 1)) * (W - 2 * PAD)}
              y1={0} y2={H}
              stroke="var(--fg)"
              strokeWidth={1}
              strokeDasharray="3 2"
              opacity={0.5}
              vectorEffect="non-scaling-stroke"
            />
          )}

          <rect
            x={0} y={0} width={W} height={H}
            fill="transparent"
            onMouseMove={onMouseMove}
            onMouseLeave={onMouseLeave}
            {...(onSelectWindow ? brush.handlers : {})}
            style={{ cursor: 'crosshair', ...(onSelectWindow ? brush.handlers.style : {}) }}
          />
        </svg>

        <BrushLabel selection={brush.selection} />

        {tooltip && !brush.active && (
          <StackedTooltip
            tooltip={tooltip}
            bands={bands}
            at={at}
            total={totalAt}
            paidIn={showInvested ? invested[at] : null}
          />
        )}

        <div className="flex justify-between mt-1.5 font-[var(--font-mono)] text-[10px] text-[var(--fg-3)]">
          <span>{simulation.dates[0]}</span>
          <span>{simulation.dates[simulation.dates.length - 1]}</span>
        </div>

        {brush.refused && (
          <p role="status" className="text-[11.5px] text-[var(--warning)] m-0 mt-1.5">
            That was too short a stretch to simulate — drag across a wider one.
          </p>
        )}
      </div>

      <ul className="list-none flex flex-wrap gap-x-4 gap-y-1.5 m-0 mt-3 p-0">
        {showInvested && (
          <li className="flex items-center gap-1.5 text-[11.5px]">
            <span
              className="w-2.5 h-0 flex-none border-t-2 border-dashed"
              style={{ borderColor: INVESTED_COLOR }}
              aria-hidden="true"
            />
            <span className="font-[var(--font-mono)] font-bold text-[var(--fg)]">Paid in</span>
            <span className="text-[var(--fg-2)]">{CURRENCY.format(invested[at])}</span>
          </li>
        )}
        {bands.map(band => {
          const value = band.values[at];
          const share = totalAt > 0 ? (value / totalAt) * 100 : 0;
          return (
            <li key={band.key} className="flex items-center gap-1.5 text-[11.5px]">
              <span
                className="w-2.5 h-2.5 rounded-[3px] flex-none"
                style={{ background: band.color }}
                aria-hidden="true"
              />
              <span className="font-[var(--font-mono)] font-bold text-[var(--fg)]">{band.key}</span>
              <span className="text-[var(--fg-2)]">{share.toFixed(1)}%</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
});

/**
 * What every band was worth on the hovered date. The dashboard's
 * ChartTooltip answers for one series, which is the wrong shape here —
 * the question a stacked chart raises is how the total was divided, not
 * what it was.
 */
function StackedTooltip({ tooltip, bands, at, total, paidIn }) {
  const position = tooltip.alignRight
    ? { right: `${Math.max(0, 98 - tooltip.pctX)}%` }
    : { left: `${Math.max(0, tooltip.pctX - 2)}%` };

  // Largest first, and never more than fits in a tooltip somebody is
  // reading with a mouse held still.
  const ranked = [...bands]
    .map(band => ({ ...band, value: band.values[at] }))
    .filter(band => band.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);

  return (
    <div
      className="absolute top-4 bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-md)] px-3 py-2 pointer-events-none shadow-[var(--shadow-lg)] whitespace-nowrap z-20"
      style={position}
    >
      <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] mb-1">{tooltip.label}</div>
      <div className="text-[14px] font-extrabold tabular-nums tracking-tight text-[var(--fg)]">
        {CURRENCY.format(total)}
      </div>
      {/* The two numbers that matter side by side on a funded portfolio:
          what it is worth, and what it cost to get there by this date. */}
      {paidIn != null && (
        <div className="font-[var(--font-mono)] text-[10.5px] text-[var(--fg-2)] mt-0.5">
          {CURRENCY.format(paidIn)} paid in ·{' '}
          <span style={{ color: total - paidIn >= 0 ? 'var(--success)' : 'var(--danger)' }}>
            {total - paidIn >= 0 ? '+' : '−'}{CURRENCY.format(Math.abs(total - paidIn))}
          </span>
        </div>
      )}
      <div className="mb-1.5" />
      <ul className="list-none m-0 p-0 flex flex-col gap-0.5">
        {ranked.map(band => (
          <li key={band.key} className="flex items-center gap-2 text-[11.5px]">
            <span
              className="w-2 h-2 rounded-[2px] flex-none"
              style={{ background: band.color }}
              aria-hidden="true"
            />
            <span className="font-[var(--font-mono)] text-[var(--fg-1)] flex-1">{band.key}</span>
            <span className="font-[var(--font-mono)] text-[var(--fg)] tabular-nums">
              {CURRENCY.format(band.value)}
            </span>
            <span className="font-[var(--font-mono)] text-[var(--fg-2)] tabular-nums w-[42px] text-right">
              {total > 0 ? ((band.value / total) * 100).toFixed(1) : '0.0'}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
