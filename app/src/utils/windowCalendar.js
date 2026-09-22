/**
 * windowCalendar — what a date typed or clicked into the portfolio window's
 * fields means, and the calendar arithmetic behind the popover (issue #156).
 * Pure: no DOM, no storage, no clock unless a caller asks for `today()`, which
 * is why the seams below are tested with literal dates and nothing faked.
 *
 * **One rule for typing and clicking.** `editWindow` takes the window in force,
 * the bound being edited and a date (text from the box, or an ISO date from the
 * calendar — the same function reads both) and answers what to do:
 *
 *   commit   the window is usable: send it
 *   hold     the date is fine but the other bound is not there yet (Max before
 *            its first run): keep it, send nothing
 *   problem  it cannot be a window, and `message` says why
 *
 * Only the edited bound ever changes, so picking a day cannot move the date
 * beside it. `windowProblem` is the backend's `resolve_window` restated (a start
 * before the end, an end not in the future) so an unusable window is a message
 * next to the box and not a 400.
 *
 * **"Today" is the UTC date**, the one the backend checks an `end` against. The
 * user's local date can be a day ahead of it, and offering that day would be
 * offering one the server calls the future.
 *
 * **1970 is a suggestion, not a rule** (`CALENDAR_FLOOR`). The calendar will not
 * navigate before it — most stocks have nothing older — but `windowProblem` has no
 * 1970 in it: a typed date or a link before it is an ordinary window, and the
 * backend has no floor of its own. Where the window already reaches past it, the
 * floor gives way (`pickableRange` never returns an empty range) rather than
 * leaving a calendar with every day disabled. Year 0 is refused, because Python's
 * `date.fromisoformat` refuses it.
 *
 * **Dates are built with `setUTCFullYear`**, never `Date.UTC` or `new Date(y, …)`:
 * both read a year under 100 as 19xx, and a typed `0002-01-01` can reach here.
 * Weeks start on Monday, the way the storage tiers' weekly rows are anchored, and
 * a month is always drawn as six weeks so the popover keeps one height.
 */

const TYPED_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** The earliest day the calendar will navigate to. See the model above. */
const CALENDAR_FLOOR = '1970-01-01';

// ── Small date arithmetic, on ISO strings ───────────────────────────────

const pad = (n, width = 2) => String(n).padStart(width, '0');

/** `YYYY-MM-DD`, `month` counted from 1. */
export const isoDate = (year, month, day) => `${pad(year, 4)}-${pad(month)}-${pad(day)}`;

/** `[year, month, day]` of an ISO date, `month` counted from 1. */
export const dateParts = (iso) => iso.split('-').map(Number);

/** An ISO date as a UTC `Date`, safe for years under 100. */
export function utcDate(iso) {
  const [year, month, day] = dateParts(iso);
  const t = new Date(0);
  t.setUTCFullYear(year, month - 1, day);
  return t;
}

const isLeap = (year) => (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;

/** Days in a month, `month` counted from 1. */
function daysInMonth(year, month) {
  if (month === 2) return isLeap(year) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

/** An ISO date `days` away. */
export function addDays(iso, days) {
  const t = utcDate(iso);
  t.setUTCDate(t.getUTCDate() + days);
  return isoDate(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
}

/** The same day `delta` months away, or that month's last day if it has no
 *  such day: 31 January plus a month is 28 February, not a day in March. */
export function shiftMonth(iso, delta) {
  const [year, month, day] = dateParts(iso);
  const index = year * 12 + (month - 1) + delta;
  const y = Math.floor(index / 12);
  const m = (index % 12) + 1;
  return isoDate(y, m, Math.min(day, daysInMonth(y, m)));
}

/** The nearest day inside `range`. */
export const clampToRange = (iso, { min, max }) => (iso < min ? min : iso > max ? max : iso);

// ── Typed dates and what they do to the window ──────────────────────────

/** The ISO date the text says, or null: a real calendar date and nothing else,
 *  so `2021-02-30` and `2020-1-5` are refused. Slash dates are refused on
 *  purpose — day-first and month-first cannot be told apart. */
export function parseTypedDate(text) {
  const trimmed = String(text ?? '').trim();
  const match = TYPED_DATE.exec(trimmed);
  if (!match) return null;
  const [year, month, day] = match.slice(1).map(Number);
  if (year < 1 || month < 1 || month > 12) return null;
  if (day < 1 || day > daysInMonth(year, month)) return null;
  return trimmed;
}

/** The UTC date, which is the one the backend's `end` is checked against. */
export function today(now = new Date()) {
  return now.toISOString().slice(0, 10);
}

/**
 * Why a window cannot be used, or null if it can. A bound that is missing is not
 * a problem yet; one that is present is held to every rule it can be held to on
 * its own, so an end in the future is said before the start arrives.
 */
export function windowProblem({ start, end }, now = today()) {
  if (start && !parseTypedDate(start)) return 'The start date is not a full date yet.';
  if (end && !parseTypedDate(end)) return 'The end date is not a full date yet.';
  if (end && end > now) return 'The end date cannot be in the future.';
  if (start && end && start >= end) return 'The start date has to come before the end date.';
  return null;
}

/** What one date does to the window: `commit`, `hold` or `problem`. See above. */
export function editWindow(current, field, text, now) {
  const iso = parseTypedDate(text);
  if (!iso) {
    return { status: 'problem', message: `Type the ${field} date as YYYY-MM-DD, for example 2020-03-16.` };
  }
  const next = { ...current, [field]: iso };
  const message = windowProblem(next, now);
  if (message) return { status: 'problem', message };
  if (!next.start || !next.end) return { status: 'hold', draft: next };
  return { status: 'commit', window: next };
}

// ── Which days the calendar offers ──────────────────────────────────────

/**
 * The days a calendar opened on `field` may offer, inclusive, and never empty.
 * A start has to come before the end and an end after the start, so the calendar
 * disables the days that would make a window `windowProblem` refuses instead of
 * accepting the click and answering it afterwards. A bound that is missing
 * constrains nothing beyond the floor and today, and where the other bound is
 * itself out of reach of the floor the floor gives way.
 */
export function pickableRange(field, { start, end }, now) {
  if (field === 'start') {
    const max = addDays(end || now, -1);
    return { min: CALENDAR_FLOOR < max ? CALENDAR_FLOOR : max, max };
  }
  const min = addDays(start || CALENDAR_FLOOR, 1);
  const floored = min < CALENDAR_FLOOR ? CALENDAR_FLOOR : min;
  return { min: floored > now ? now : floored, max: now };
}

// ── Which days fill a month ─────────────────────────────────────────────

/** 0 for Monday … 6 for Sunday, the way an ISO week counts them. */
const weekdayIndex = (iso) => (utcDate(iso).getUTCDay() + 6) % 7;

/**
 * The month as six weeks of seven days, Monday first, `month` counted from 1.
 * Always six, so the popover is the same height in every month rather than
 * jumping as you page through them; the days that spill in from either side
 * are there to fill the rows and are marked `inMonth: false`, so the caller
 * can draw them quieter.
 */
export function monthGrid(year, month) {
  const first = isoDate(year, month, 1);
  const start = addDays(first, -weekdayIndex(first));
  const prefix = first.slice(0, 7);
  return Array.from({ length: 6 }, (_, week) =>
    Array.from({ length: 7 }, (_, day) => {
      const iso = addDays(start, week * 7 + day);
      return { iso, inMonth: iso.startsWith(prefix) };
    })
  );
}

// ── Where the keyboard goes ─────────────────────────────────────────────

/**
 * Where a key sends the calendar's cursor, or null for a key that is not a
 * way of moving it. The standard date-grid keys: arrows a day or a week, Page
 * Up and Down a month, Home and End the ends of the (Monday-first) week. The
 * answer is clamped into `range`, so the cursor can never rest on a day the
 * calendar has disabled.
 */
export function moveFocus(iso, key, range) {
  const moves = {
    ArrowLeft: () => addDays(iso, -1),
    ArrowRight: () => addDays(iso, 1),
    ArrowUp: () => addDays(iso, -7),
    ArrowDown: () => addDays(iso, 7),
    PageUp: () => shiftMonth(iso, -1),
    PageDown: () => shiftMonth(iso, 1),
    Home: () => addDays(iso, -weekdayIndex(iso)),
    End: () => addDays(iso, 6 - weekdayIndex(iso)),
  };
  const move = moves[key];
  return move ? clampToRange(move(), range) : null;
}
