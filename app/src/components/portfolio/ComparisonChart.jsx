/**
 * ComparisonChart — several portfolios, and whatever they are being held
 * up against, on one pair of axes.
 *
 * **Percent is the default, and it has to be.** A $1,000 portfolio next
 * to a $100,000 one is a flat line under a mountain when both are drawn
 * in dollars, and the flat one is not flat — it is the same shape at a
 * different size. Normalising each line to its own starting value asks
 * the question people actually have ("which grew faster?"); the dollar
 * view answers the other one ("what would I have ended up with?"), and
 * the toggle is a re-draw of data already in hand rather than a refetch.
 *
 * **Lines do not share a calendar, and must not be drawn as though they
 * did.** `prices` tiers history by age (issue #10), so a portfolio of
 * tracked stocks comes back weekly for anything one to five years old,
 * while an ETF benchmark — which has no rows of its own and is answered
 * live — comes back daily for the whole window. Over five years that is
 * 461 rows against 1254.
 *
 * So each line is positioned by its dates rather than by its place in a
 * merged list, drawn through its own observations however far apart they
 * fall, and read at a hovered date as of its last observation. Snapping
 * every line onto one shared index instead left the weekly one as a few
 * hundred isolated points — an SVG moveto with no lineto draws nothing,
 * so the line vanished while its values still appeared under the cursor.
 *
 * Two portfolios can also cover different stretches of the same window —
 * one holding something that lists later starts later — and a line that
 * simply begins further along is the honest way to show that.
 *
 * A benchmark is drawn dashed. It is not a portfolio anybody owns here,
 * and the eye should be able to tell without reading the legend. *
 * Sized like PortfolioChart, whose slot it takes: stretched horizontally
 * (so no text inside the SVG), drawn in pixels vertically, with a height
 * that runs to the bottom of the first screenful between 240px and 600px
 * (issue #139, useFillHeight).
 */
import { memo, useCallback, useMemo, useState } from 'react';
import { useChartBrush } from '../../hooks/useChartBrush';
import { useFillHeight } from '../../hooks/useFillHeight';
import { BrushLabel, BrushShading } from '../charts/BrushOverlay';

const W = 360;
const PAD = 4;

/** The plot's height range in pixels — the same range, for the same
 *  reasons, as PortfolioChart's (issue #139): the old fixed height as
 *  the floor, and a ceiling so a tall monitor does not make a poster. */
const PLOT_MIN = 240;
const PLOT_MAX = 600;

const PALETTE = ['#7849ff', '#2a8aff', '#2bd47d', '#ffb547', '#ff4d6d', '#00c2c7'];

const CURRENCY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

const MODES = [
  { key: 'percent', label: '%' },
  { key: 'value', label: '$' },
];

function formatValue(value, mode) {
  if (value === null || value === undefined) return '—';
  if (mode === 'value') return CURRENCY.format(value);
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(1)}%`;
}

const DAY = 24 * 60 * 60 * 1000;

function time(date) {
  return new Date(date + "T00:00:00Z").getTime();
}

/**
 * Put every run on one time axis, and on one scale.
 *
 * In percent mode each line is measured from its own first value, so all
 * of them start at zero however much money they started with - and off
 * the flow-free series rather than the value, so a line paid into monthly
 * is not credited with its own deposits (#67). Without that, a portfolio
 * funded with $500 a month draws a return three times the one the summary
 * table beside it reports for the same line. Value mode still plots the
 * value, because there the deposits are the point.
 *
 * Each line keeps two things: `observations`, the points it actually has,
 * which is what gets drawn; and `readings`, one value per date on the
 * shared axis, carried forward from the last observation. A weekly line
 * does have a value on a Wednesday, in the sense that its last close
 * still describes what it was worth — the same forward-fill the
 * simulation applies inside a run (services/portfolio.py). Before a
 * line's first observation there is nothing to carry, and it reads as
 * absent.
 */
function buildSeries(runs, mode) {
  const dates = [...new Set(runs.flatMap(run => run.simulation?.dates || []))].sort();
  const first = dates.length ? time(dates[0]) : 0;
  const span = dates.length ? Math.max(time(dates[dates.length - 1]) - first, DAY) : DAY;

  const series = runs.map((run, i) => {
    const simulation = run.simulation;
    const observations = [];
    const readings = new Array(dates.length).fill(null);

    if (simulation) {
      // `unitValue` is null unless contributions moved the two apart, so
      // an ordinary run reads exactly the series it always did.
      const performance = simulation.unitValue || simulation.total;
      const base = performance[0] || 1;
      const own = new Map();
      simulation.dates.forEach((date, j) => {
        const value = mode === "value"
          ? simulation.total[j]
          : (performance[j] / base - 1) * 100;
        own.set(date, value);
        observations.push({ at: (time(date) - first) / span, value });
      });
      let carried = null;
      dates.forEach((date, j) => {
        if (own.has(date)) carried = own.get(date);
        readings[j] = carried;
      });
    }

    return { ...run, observations, readings, color: PALETTE[i % PALETTE.length] };
  });

  const values = series.flatMap(line => line.observations.map(point => point.value));
  const min = values.length ? Math.min(...values, mode === "percent" ? 0 : Infinity) : 0;
  const max = values.length ? Math.max(...values) : 1;
  return { dates, series, min, max: max === min ? min + 1 : max };
}

export const ComparisonChart = memo(function ComparisonChart({ runs, stale, onSelectWindow }) {
  const [mode, setMode] = useState('percent');
  const [hoverIdx, setHoverIdx] = useState(null);

  const { dates, series, min, max } = useMemo(() => buildSeries(runs, mode), [runs, mode]);
  // Pixels vertically (viewBox height = on-screen height), so a taller
  // plot is a taller drawing rather than a stretched one.
  const { outerRef, plotRef, height: H } = useFillHeight(PLOT_MIN, PLOT_MAX);


  // Positioned by date, not by place in the merged list: a line sampled
  // weekly has a quarter of the points of a daily one over the same
  // stretch, and spacing them evenly would stretch its half of the chart.
  const axisStart = dates.length ? time(dates[0]) : 0;
  const axisSpan = dates.length
    ? Math.max(time(dates[dates.length - 1]) - axisStart, DAY)
    : DAY;
  const xAt = fraction => PAD + fraction * (W - 2 * PAD);
  const x = i => xAt((time(dates[i]) - axisStart) / axisSpan);
  const y = value => H - ((value - min) / (max - min)) * H;

  // Drawn through the line's own observations, however far apart they
  // fall. A gap in the shared axis is not a gap in the line.
  const paths = series.map(line => ({
    ...line,
    d: line.observations
      .map((point, i) => (i ? "L" : "M") + xAt(point.at).toFixed(2) + " " + y(point.value).toFixed(2))
      .join(" "),
  }));

  // The nearest date in time to a position across the plot, since the
  // axis is time and the dates on it are not evenly spread.
  const resolve = useCallback((fraction) => {
    if (dates.length === 0) return null;
    const target = axisStart + ((fraction * W - PAD) / (W - 2 * PAD)) * axisSpan;
    let nearest = 0;
    let best = Infinity;
    dates.forEach((date, i) => {
      const distance = Math.abs(time(date) - target);
      if (distance < best) { best = distance; nearest = i; }
    });
    return { index: nearest, date: dates[nearest] };
  }, [dates, axisStart, axisSpan]);

  const brush = useChartBrush({ resolve, onSelect: onSelectWindow || (() => {}) });

  // Every line failed, so there is no axis to draw one against. Checked
  // after the hooks above rather than before them: an early return has to
  // come after every hook a render can make, or the next render makes a
  // different set.
  if (dates.length === 0) {
    return (
      <p className="text-[12.5px] text-[var(--warning)] leading-relaxed m-0 mb-4">
        None of these lines could be simulated over this window.
      </p>
    );
  }

  const onMouseMove = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    const relative = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width));
    const found = resolve(relative);
    if (found) setHoverIdx(found.index);
  };

  const at = hoverIdx ?? dates.length - 1;
  // Zero is where a percent chart's eye goes; in dollars it is usually
  // off the bottom of the scale and not worth a line.
  const zeroY = mode === 'percent' && min < 0 && max > 0 ? y(0) : null;

  return (
    <div ref={outerRef} className="mb-6">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
        <div className="eyebrow">
          {mode === 'percent' ? 'RETURN, EACH FROM ITS OWN START' : 'VALUE'}
        </div>
        <div className="inline-flex p-[3px] bg-[var(--bg-3)] rounded-[var(--radius-md)] gap-[1px]">
          {MODES.map(option => {
            const active = mode === option.key;
            return (
              <button
                key={option.key}
                onClick={() => setMode(option.key)}
                aria-pressed={active}
                aria-label={option.key === 'percent' ? 'Show percentage return' : 'Show dollar value'}
                className="px-3 py-[5px] border-none rounded-[7px] cursor-pointer font-[var(--font-mono)] text-xs transition-all duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
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

      <div
        className="relative bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] p-4 pl-16"
        style={{ opacity: stale ? 0.6 : 1, transition: 'opacity 120ms' }}
      >
        {[1, 0.5, 0].map(fraction => (
          <span
            key={fraction}
            className="absolute left-2 font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] -translate-y-1/2"
            style={{ top: `calc(1rem + ${(1 - fraction) * H}px)` }}
          >
            {formatValue(min + (max - min) * fraction, mode)}
          </span>
        ))}

        <svg
          ref={plotRef}
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          width="100%"
          className="block"
          style={{ height: `${H}px` }}
          role="img"
          aria-label="Compared portfolios over the selected window"
        >
          {[0.25, 0.5, 0.75].map(fraction => (
            <line
              key={fraction}
              x1={0} x2={W} y1={H * fraction} y2={H * fraction}
              stroke="var(--divider)" strokeWidth={1} vectorEffect="non-scaling-stroke"
            />
          ))}

          {zeroY !== null && (
            <line
              x1={0} x2={W} y1={zeroY} y2={zeroY}
              stroke="var(--fg-3)" strokeWidth={1} vectorEffect="non-scaling-stroke"
            />
          )}

          {paths.map(line => (
            <path
              key={line.key}
              d={line.d}
              fill="none"
              stroke={line.color}
              strokeWidth={line.kind === 'benchmark' ? 1.5 : 2}
              strokeDasharray={line.kind === 'benchmark' ? '5 3' : undefined}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}

          <BrushShading selection={brush.selection} width={W} height={H} />

          {hoverIdx !== null && !brush.active && (
            <line
              x1={x(at)} x2={x(at)} y1={0} y2={H}
              stroke="var(--fg)" strokeWidth={1} strokeDasharray="3 2" opacity={0.5}
              vectorEffect="non-scaling-stroke"
            />
          )}

          <rect
            x={0} y={0} width={W} height={H} fill="transparent"
            onMouseMove={onMouseMove}
            onMouseLeave={() => setHoverIdx(null)}
            {...(onSelectWindow ? brush.handlers : {})}
            style={{ cursor: 'crosshair', ...(onSelectWindow ? brush.handlers.style : {}) }}
          />
        </svg>

        <BrushLabel selection={brush.selection} />

        {hoverIdx !== null && !brush.active && (
          <div
            className="absolute top-4 bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-md)] px-3 py-2 pointer-events-none shadow-[var(--shadow-lg)] whitespace-nowrap z-20"
            style={
              (x(at) / W) * 100 >= 55
                ? { right: `${Math.max(0, 98 - (x(at) / W) * 100)}%` }
                : { left: `${Math.max(0, (x(at) / W) * 100 - 2)}%` }
            }
          >
            <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] mb-1">{dates[at]}</div>
            <ul className="list-none m-0 p-0 flex flex-col gap-0.5">
              {[...series]
                .sort((a, b) => (b.readings[at] ?? -Infinity) - (a.readings[at] ?? -Infinity))
                .map(line => (
                  <li key={line.key} className="flex items-center gap-2 text-[11.5px]">
                    <span
                      className="w-2 h-2 rounded-[2px] flex-none"
                      style={{ background: line.color, opacity: line.kind === 'benchmark' ? 0.6 : 1 }}
                      aria-hidden="true"
                    />
                    <span className="font-[var(--font-mono)] text-[var(--fg-1)] flex-1">{line.label}</span>
                    <span className="font-[var(--font-mono)] text-[var(--fg)] tabular-nums">
                      {formatValue(line.readings[at], mode)}
                    </span>
                  </li>
                ))}
            </ul>
          </div>
        )}

        <div className="flex justify-between mt-1.5 font-[var(--font-mono)] text-[10px] text-[var(--fg-3)]">
          <span>{dates[0]}</span>
          <span>{dates[dates.length - 1]}</span>
        </div>

        {brush.refused && (
          <p role="status" className="text-[11.5px] text-[var(--warning)] m-0 mt-1.5">
            That was too short a stretch to simulate — drag across a wider one.
          </p>
        )}
      </div>

      <ul className="list-none flex flex-wrap gap-x-4 gap-y-1.5 m-0 mt-3 p-0">
        {series.map(line => (
          <li key={line.key} className="flex items-center gap-1.5 text-[11.5px]">
            <span
              className="w-4 h-0 flex-none border-t-2"
              style={{
                borderColor: line.color,
                borderTopStyle: line.kind === 'benchmark' ? 'dashed' : 'solid',
              }}
              aria-hidden="true"
            />
            <span className="font-semibold text-[var(--fg)]">{line.label}</span>
            {line.kind === 'benchmark' && <span className="eyebrow">BENCHMARK</span>}
            <span className="font-[var(--font-mono)] text-[var(--fg-2)]">
              {formatValue(line.readings[at], mode)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
});
