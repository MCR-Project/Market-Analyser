/**
 * candles — turns the rows `/api/series` answers into the candles a price
 * chart draws (issue #152). Pure: no storage, no network, no DOM, which is
 * what lets its rules be pinned by tests rather than by looking at a chart.
 *
 * A row is not a candle. `prices` tiers history by age (README, "How prices
 * are stored"), so one window mixes daily, weekly and monthly rows, and a
 * chart drawing one candle per row would change what a candle means halfway
 * along its own axis. Every candle on a chart instead covers ONE span, picked
 * by the timeframe and small enough to keep the count readable in the
 * narrowest chart (the fund card is ~280px wide): a day for 1W and 1M, a week
 * for 1Y, a month for 5Y. Rows are folded into their span the way
 * `scripts/fetch_daily.py`'s `_resample` folds days into a stored bucket: the
 * first open, the highest high, the lowest low, the last close.
 *
 * Four things this module decides, each of them what a reader would
 * otherwise have to be told:
 *
 * - **A stored coarse row covers its whole bucket, not its anchor.** A weekly
 *   row is dated by its Monday but is the whole week's trading (Monday to
 *   Friday); a monthly row is the whole month. The tooltip's "days covered"
 *   reads from that, not from a date that names one day.
 * - **A week straddling a month end belongs to the month its Monday is in.**
 *   A weekly row carries no finer date, so a 5Y month candle cannot split
 *   it. The candle then says so - its span runs past the month's own last
 *   day - instead of pretending the month ended cleanly.
 * - **Edge candles are drawn as they are.** The newest candle is a stretch
 *   still forming and the oldest can be clipped by where the window opens;
 *   each covers whatever days it actually holds, and says which.
 * - **Absence is a gap, never a flat candle (invariant 7).** A candle with
 *   any of its four prices missing - or built from a row that lacks one - has
 *   open, high and low all `null` and `complete: false`; its close is kept as
 *   it stands (every row the API sends has one) so the chart's own return
 *   figures still read. One missing day
 *   blanks the whole stretch it sits in: the stretch's high is unknown
 *   without that day's, and a smaller number would be a range nobody
 *   measured. Zero is a price; only null and undefined are absent.
 */

const SPAN_BY_TIMEFRAME = { '1W': 'day', '1M': 'day', '1Y': 'week', '5Y': 'month' };

const DAY_MS = 86_400_000;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** What one candle covers on a chart showing `timeframe`: `day`, `week` or
 *  `month`. An unknown timeframe reads like the 1Y default - the same
 *  fallback `useLiveSeries` makes for its period. */
export function candleSpan(timeframe) {
  return SPAN_BY_TIMEFRAME[timeframe] ?? 'week';
}

/**
 * The candles for `rows` (oldest first, as the API sends them) at
 * `timeframe`'s span: `{ from, to, open, high, low, close, complete }`, where
 * `from`/`to` are the first and last day the candle covers as ISO dates. The
 * rows are not modified.
 */
export function toCandles(rows, timeframe) {
  if (!rows || rows.length === 0) return [];
  const span = candleSpan(timeframe);

  // Named for what they become, not "buckets": that word is the storage
  // tiers' for a coarse row (CONTEXT.md), which is exactly what these are not.
  const stretches = new Map();
  for (const row of rows) {
    const key = stretchKey(row, span);
    const to = lastDayCovered(row);
    const stretch = stretches.get(key);
    if (!stretch) {
      stretches.set(key, { from: row.date, to, rows: [row] });
    } else {
      stretch.to = to;
      stretch.rows.push(row);
    }
  }

  return [...stretches.values()].map(({ from, to, rows: inside }) => {
    const close = inside[inside.length - 1].close;
    const complete = inside.every(
      (r) => isPrice(r.open) && isPrice(r.high) && isPrice(r.low) && isPrice(r.close)
    );
    if (!complete) {
      return { from, to, open: null, high: null, low: null, close, complete: false };
    }
    return {
      from,
      to,
      open: inside[0].open,
      high: Math.max(...inside.map((r) => r.high)),
      low: Math.min(...inside.map((r) => r.low)),
      close,
      complete: true,
    };
  });
}

/** How a candle's span reads in its tooltip: "Mar 2, 2026" for one day,
 *  "Mar 2 – Mar 6, 2026" for a stretch, the year on both ends only when the
 *  two differ. Read from the days the candle covers, never from a month or
 *  week name that would claim more than it holds. */
export function candleLabel({ from, to }) {
  if (from === to) return shortDate(from, true);
  const sameYear = from.slice(0, 4) === to.slice(0, 4);
  return `${shortDate(from, !sameYear)} – ${shortDate(to, true)}`;
}

// ── Where a candle sits ───────────────────────────────────────────────────
// In the plot's own 360-unit space, the same one `AreaChart` and
// `useChartHover` use. The chart is stretched to its box
// (`preserveAspectRatio="none"`), so these are fractions of the width, not
// pixels. Candles take even slots rather than the line's evenly spaced
// points: a point can sit on the plot's edge, a candle has a width and would
// hang out of it.

export const PLOT_WIDTH = 360;
export const PLOT_PAD = 4;

/** How wide each of `count` candles' slots is. */
export function candleSlotWidth(count) {
  return (PLOT_WIDTH - 2 * PLOT_PAD) / Math.max(1, count);
}

/** The x the candle at `index` of `count` is centred on. */
export function candleCentre(index, count) {
  return PLOT_PAD + (index + 0.5) * candleSlotWidth(count);
}

/** The candle a cursor at `x` is over, clamped to the nearest one when it is
 *  beyond either end of the plot. */
export function candleIndexAt(x, count) {
  const index = Math.floor((x - PLOT_PAD) / candleSlotWidth(count));
  return Math.max(0, Math.min(count - 1, index));
}

// ── Dates ─────────────────────────────────────────────────────────────────
// Arithmetic on UTC midnights, so a viewer's time zone can never move a date
// across a day boundary - `new Date('2026-03-02T00:00:00')` is local time.

function parts(iso) {
  const [year, month, day] = iso.split('-').map(Number);
  return { year, month, day };
}

function utcMs(iso) {
  const { year, month, day } = parts(iso);
  return Date.UTC(year, month - 1, day);
}

function isoOf(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

function mondayOf(iso) {
  const ms = utcMs(iso);
  const sinceMonday = (new Date(ms).getUTCDay() + 6) % 7;
  return isoOf(ms - sinceMonday * DAY_MS);
}

function lastDayOfMonth(iso) {
  const { year, month } = parts(iso);
  return isoOf(Date.UTC(year, month, 0));
}

function shortDate(iso, withYear) {
  const { year, month, day } = parts(iso);
  return `${MONTHS[month - 1]} ${day}` + (withYear ? `, ${year}` : '');
}

// ── Rows ──────────────────────────────────────────────────────────────────

function stretchKey(row, span) {
  if (span === 'day') return row.date;
  if (span === 'week') return mondayOf(row.date);
  return row.date.slice(0, 7);
}

/** The last day a row's own bucket holds. A daily row is its date; a weekly
 *  one is dated by its Monday and holds the trading week to Friday; a monthly
 *  one holds the whole month. */
function lastDayCovered(row) {
  if (row.granularity === 'W') return isoOf(utcMs(row.date) + 4 * DAY_MS);
  if (row.granularity === 'M') return lastDayOfMonth(row.date);
  return row.date;
}

function isPrice(value) {
  return Number.isFinite(value);
}
