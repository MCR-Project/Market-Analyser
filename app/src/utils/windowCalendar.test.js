/**
 * windowCalendar — the seams the window picker is tested at (issue #156).
 * What a typed or clicked date does to a window, which days the calendar may
 * offer, which days fill a month and where the keyboard goes are all answered
 * here, so the popover that draws them stays too thin to need a test of its own.
 *
 * Every date below is a literal, and every expected value a plain fact about
 * the calendar (2024 was a leap year, 2026-09-21 is a Monday) that a reader can
 * check without running the code.
 *
 * Plain functions and inline data, no DOM.
 */
import { expect, test } from 'vitest';
import { editWindow, monthGrid, moveFocus, parseTypedDate, pickableRange } from './windowCalendar';

const TODAY = '2026-09-21';
const WINDOW = { start: '2020-01-01', end: '2021-01-01' };

// ── Typed dates ─────────────────────────────────────────────────────────

test('a real YYYY-MM-DD date is read as itself, ignoring the spaces around it', () => {
  expect(parseTypedDate('2020-03-16')).toBe('2020-03-16');
  expect(parseTypedDate('  2020-03-16 ')).toBe('2020-03-16');
});

test('text that is not a real calendar date is refused, however date-shaped', () => {
  expect(parseTypedDate('2021-02-30')).toBeNull(); // February has no 30th
  expect(parseTypedDate('2023-02-29')).toBeNull(); // 2023 was not a leap year
  expect(parseTypedDate('2020-13-01')).toBeNull();
  expect(parseTypedDate('2020-00-10')).toBeNull();
  expect(parseTypedDate('2020-1-5')).toBeNull(); // not zero-padded
  expect(parseTypedDate('20200316')).toBeNull();
  expect(parseTypedDate('16/03/2020')).toBeNull(); // day-first or month-first: ambiguous
  expect(parseTypedDate('')).toBeNull();
  expect(parseTypedDate(null)).toBeNull();
});

test('a leap day is a real date in a leap year', () => {
  expect(parseTypedDate('2024-02-29')).toBe('2024-02-29');
});

test('a date before 1970 is still a date: the calendar stops there, typing does not', () => {
  expect(parseTypedDate('1965-05-04')).toBe('1965-05-04');
});

test('year 0 is not a date, since the backend would answer it with a 400', () => {
  expect(parseTypedDate('0000-01-01')).toBeNull();
  expect(parseTypedDate('0001-01-01')).toBe('0001-01-01');
});

// ── What a date does to the window ──────────────────────────────────────

test('changing one bound of a complete window commits it and leaves the other alone', () => {
  expect(editWindow(WINDOW, 'start', '2019-05-04', TODAY)).toEqual({
    status: 'commit',
    window: { start: '2019-05-04', end: '2021-01-01' },
  });
  expect(editWindow(WINDOW, 'end', '2022-06-30', TODAY)).toEqual({
    status: 'commit',
    window: { start: '2020-01-01', end: '2022-06-30' },
  });
});

test('a start that is not before the end is a problem, and says which way round it has to be', () => {
  const problem = {
    status: 'problem',
    message: 'The start date has to come before the end date.',
  };
  expect(editWindow(WINDOW, 'start', '2021-06-01', TODAY)).toEqual(problem);
  expect(editWindow(WINDOW, 'start', '2021-01-01', TODAY)).toEqual(problem); // the same day is not before
  expect(editWindow(WINDOW, 'end', '2019-12-31', TODAY)).toEqual(problem);
});

test('an end after today is a problem, but today itself is fine', () => {
  expect(editWindow(WINDOW, 'end', '2026-09-22', TODAY)).toEqual({
    status: 'problem',
    message: 'The end date cannot be in the future.',
  });
  expect(editWindow(WINDOW, 'end', '2026-09-21', TODAY).status).toBe('commit');
});

test('text that is not a date is a problem that says what a date looks like', () => {
  expect(editWindow(WINDOW, 'start', '2021-02-30', TODAY)).toEqual({
    status: 'problem',
    message: 'Type the start date as YYYY-MM-DD, for example 2020-03-16.',
  });
  expect(editWindow(WINDOW, 'end', '', TODAY)).toEqual({
    status: 'problem',
    message: 'Type the end date as YYYY-MM-DD, for example 2020-03-16.',
  });
});

test('a date typed before the other bound exists is held, not committed', () => {
  expect(editWindow({ start: '', end: '' }, 'end', '2021-12-31', TODAY)).toEqual({
    status: 'hold',
    draft: { start: '', end: '2021-12-31' },
  });
  expect(editWindow({ start: null, end: '2021-12-31' }, 'end', '2021-06-30', TODAY)).toEqual({
    status: 'hold',
    draft: { start: null, end: '2021-06-30' },
  });
});

test('a held date is still held to the rules it can be held to alone', () => {
  expect(editWindow({ start: '', end: '' }, 'end', '2026-12-31', TODAY)).toEqual({
    status: 'problem',
    message: 'The end date cannot be in the future.',
  });
});

test('a date before 1970 commits: only the calendar stops there', () => {
  expect(editWindow(WINDOW, 'start', '1965-05-04', TODAY)).toEqual({
    status: 'commit',
    window: { start: '1965-05-04', end: '2021-01-01' },
  });
});

// ── Which days the calendar offers ──────────────────────────────────────

test('editing the start offers 1970 up to the day before the end', () => {
  expect(pickableRange('start', WINDOW, TODAY)).toEqual({ min: '1970-01-01', max: '2020-12-31' });
});

test('editing the end offers the day after the start up to today', () => {
  expect(pickableRange('end', WINDOW, TODAY)).toEqual({ min: '2020-01-02', max: TODAY });
});

test('the day before or after crosses a month, a year and a leap day correctly', () => {
  expect(pickableRange('start', { start: '2020-01-01', end: '2021-03-01' }, TODAY).max).toBe('2021-02-28');
  expect(pickableRange('start', { start: '2020-01-01', end: '2024-03-01' }, TODAY).max).toBe('2024-02-29');
  expect(pickableRange('end', { start: '2020-12-31', end: '2022-01-01' }, TODAY).min).toBe('2021-01-01');
});

test('the calendar stays at 1970 even when the window it is editing starts before it', () => {
  // A typed or linked 1965 start is a fine window; the calendar for its end still starts at 1970.
  expect(pickableRange('end', { start: '1965-05-04', end: '2021-01-01' }, TODAY).min).toBe('1970-01-01');
});

test('the calendar never has no days to offer, even when the other bound is out of its reach', () => {
  // An end before 1970: the floor gives way, rather than leaving a calendar with every day disabled.
  const before = pickableRange('start', { start: '1950-01-01', end: '1960-06-15' }, TODAY);
  expect(before.min <= before.max).toBe(true);
  expect(before.max).toBe('1960-06-14');
  // A start on today: nothing is after it, so the end's calendar still offers a day.
  const onToday = pickableRange('end', { start: TODAY, end: '' }, TODAY);
  expect(onToday.min <= onToday.max).toBe(true);
});

test('with the other bound not there yet, only the rules that stand alone apply', () => {
  const empty = { start: '', end: '' };
  expect(pickableRange('start', empty, TODAY)).toEqual({ min: '1970-01-01', max: '2026-09-20' });
  expect(pickableRange('end', empty, TODAY)).toEqual({ min: '1970-01-02', max: TODAY });
});

// ── Which days fill a month ─────────────────────────────────────────────

const flat = (grid) => grid.flat();
const inMonth = (grid) => flat(grid).filter(cell => cell.inMonth).map(cell => cell.iso);

test('a month is six weeks of seven days, so the popover never changes height', () => {
  const grid = monthGrid(2026, 9);
  expect(grid).toHaveLength(6);
  grid.forEach(week => expect(week).toHaveLength(7));
});

test('weeks start on Monday, and the days around the month are marked as outside it', () => {
  // 1 September 2026 is a Tuesday, so Monday 31 August leads the first week.
  const grid = monthGrid(2026, 9);
  expect(grid[0][0]).toEqual({ iso: '2026-08-31', inMonth: false });
  expect(grid[0][1]).toEqual({ iso: '2026-09-01', inMonth: true });
  expect(grid[5][6]).toEqual({ iso: '2026-10-11', inMonth: false });
  expect(inMonth(grid)).toHaveLength(30);
});

test('a month that begins on a Monday has no leading days', () => {
  expect(monthGrid(2026, 6)[0][0]).toEqual({ iso: '2026-06-01', inMonth: true });
});

test('February has 29 days in a leap year and 28 in another, and a Sunday start reaches back six days', () => {
  expect(inMonth(monthGrid(2024, 2))).toHaveLength(29);
  expect(inMonth(monthGrid(2026, 2))).toHaveLength(28);
  expect(monthGrid(2026, 2)[0][0].iso).toBe('2026-01-26'); // 1 Feb 2026 is a Sunday
});

test('December runs on into January of the next year', () => {
  const grid = monthGrid(2025, 12);
  expect(grid[5][6]).toEqual({ iso: '2026-01-11', inMonth: false });
});

// ── Where the keyboard goes ─────────────────────────────────────────────

const ANY = { min: '1970-01-01', max: TODAY };

test('the arrow keys move a day sideways and a week up or down, across month ends', () => {
  expect(moveFocus('2026-09-10', 'ArrowLeft', ANY)).toBe('2026-09-09');
  expect(moveFocus('2026-09-10', 'ArrowRight', ANY)).toBe('2026-09-11');
  expect(moveFocus('2026-09-10', 'ArrowUp', ANY)).toBe('2026-09-03');
  expect(moveFocus('2026-09-10', 'ArrowDown', ANY)).toBe('2026-09-17');
  expect(moveFocus('2026-06-30', 'ArrowRight', ANY)).toBe('2026-07-01');
  expect(moveFocus('2026-01-01', 'ArrowLeft', ANY)).toBe('2025-12-31');
});

test('Page Up and Page Down move a month, and a 31st lands on the last day of a shorter one', () => {
  expect(moveFocus('2026-01-31', 'PageDown', ANY)).toBe('2026-02-28');
  expect(moveFocus('2024-01-31', 'PageDown', ANY)).toBe('2024-02-29');
  expect(moveFocus('2026-03-31', 'PageUp', ANY)).toBe('2026-02-28');
  expect(moveFocus('2025-12-15', 'PageDown', ANY)).toBe('2026-01-15');
});

test('Home and End go to the Monday and the Sunday of the week', () => {
  // 16 September 2026 is a Wednesday.
  expect(moveFocus('2026-09-16', 'Home', ANY)).toBe('2026-09-14');
  expect(moveFocus('2026-09-16', 'End', ANY)).toBe('2026-09-20');
});

test('the cursor stops at the edge of what can be picked', () => {
  expect(moveFocus(TODAY, 'ArrowRight', ANY)).toBe(TODAY);
  expect(moveFocus('2026-09-18', 'ArrowDown', ANY)).toBe(TODAY);
  expect(moveFocus('1970-01-05', 'PageUp', ANY)).toBe('1970-01-01');
  const narrow = { min: '2020-01-02', max: '2020-12-31' };
  expect(moveFocus('2020-01-03', 'ArrowUp', narrow)).toBe('2020-01-02');
});

test('a key that is not a way of moving is not answered', () => {
  expect(moveFocus('2026-09-16', 'a', ANY)).toBeNull();
});
