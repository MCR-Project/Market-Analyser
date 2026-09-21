/**
 * freshness — the seam the header's Freshness indicator is tested at (issue
 * #154). `freshnessState` decides which of four states the data is in, and
 * `describeFreshness` says it in the words the header shows. The backend names
 * the deadline (`dueBy`); these compare it with the browser's own clock.
 *
 * Every time below is a literal, and `NOW` is chosen so each expected phrase is
 * plain arithmetic a reader can check: the run finished 3 hours before it.
 *
 * Plain functions and inline data, no DOM.
 */
import { expect, test } from 'vitest';
import { describeFreshness, freshnessState } from './freshness';

const HOUR = 60 * 60 * 1000;
const NOW = Date.parse('2026-09-19T03:28:00Z');

// A Friday run that finished 3 hours before NOW, due Tuesday 10:30 UTC.
const RUN = {
  finishedAt: '2026-09-19T00:28:00+00:00',
  dueBy: '2026-09-22T10:30:00+00:00',
  failed: 0,
};

const at = (isoTime) => Date.parse(isoTime);
const finishedAgo = (ms) => ({ ...RUN, finishedAt: new Date(NOW - ms).toISOString() });

// ── The state ───────────────────────────────────────────────────────────

test('a run before its deadline with nothing failed is on schedule', () => {
  expect(freshnessState(NOW, RUN)).toBe('onSchedule');
});

test('a run before its deadline with failures says so, and is still not behind', () => {
  expect(freshnessState(NOW, { ...RUN, failed: 4 })).toBe('failures');
});

test('from the deadline on, with no newer run, the data is behind', () => {
  expect(freshnessState(at('2026-09-22T10:29:59.999Z'), RUN)).toBe('onSchedule');
  expect(freshnessState(at('2026-09-22T10:30:00Z'), RUN)).toBe('behind');
  expect(freshnessState(at('2026-09-25T00:00:00Z'), RUN)).toBe('behind');
});

test('behind outranks a run that had failures: an overdue refresh makes its count old news', () => {
  expect(freshnessState(at('2026-09-23T00:00:00Z'), { ...RUN, failed: 4 })).toBe('behind');
});

test('nothing recorded is unknown, never behind and never a date', () => {
  // The backend's 200 of nulls (no Supabase, or no run yet), a failed request,
  // and a request still to be made are all "no record".
  const nulls = { finishedAt: null, dueBy: null, failed: null };
  expect(freshnessState(NOW, nulls)).toBe('unknown');
  expect(freshnessState(NOW, null)).toBe('unknown');
  expect(freshnessState(NOW, undefined)).toBe('unknown');
});

test('a record missing any one of its three fields is unknown, not a guess', () => {
  expect(freshnessState(NOW, { ...RUN, finishedAt: null })).toBe('unknown');
  expect(freshnessState(NOW, { ...RUN, dueBy: null })).toBe('unknown');
  // A null failure count is not zero: it would claim "nothing failed".
  expect(freshnessState(NOW, { ...RUN, failed: null })).toBe('unknown');
});

test('a time the browser cannot read is unknown', () => {
  expect(freshnessState(NOW, { ...RUN, dueBy: 'soon' })).toBe('unknown');
  expect(freshnessState(NOW, { ...RUN, finishedAt: 'yesterday' })).toBe('unknown');
});

// ── The words ───────────────────────────────────────────────────────────

test('on schedule says how long ago the last refresh was', () => {
  expect(describeFreshness(NOW, RUN)).toEqual({ state: 'onSchedule', text: 'Refreshed 3h ago' });
});

test('failures add how many', () => {
  expect(describeFreshness(NOW, { ...RUN, failed: 4 })).toEqual({
    state: 'failures',
    text: 'Refreshed 3h ago · 4 failed',
  });
});

test('behind says the refresh is overdue and when the last one was', () => {
  expect(describeFreshness(at('2026-09-22T10:30:00Z'), RUN)).toEqual({
    state: 'behind',
    text: 'Refresh overdue · last 3d ago',
  });
});

test('unknown says the status is unknown and nothing more', () => {
  expect(describeFreshness(NOW, null)).toEqual({ state: 'unknown', text: 'Refresh status unknown' });
});

test('the age reads in minutes under an hour, hours under a day, days after', () => {
  const ago = (ms) => describeFreshness(NOW, finishedAgo(ms)).text;
  expect(ago(5 * 60 * 1000)).toBe('Refreshed 5m ago');
  expect(ago(59 * 60 * 1000)).toBe('Refreshed 59m ago');
  expect(ago(HOUR)).toBe('Refreshed 1h ago');
  expect(ago(23 * HOUR + 59 * 60 * 1000)).toBe('Refreshed 23h ago');
  expect(ago(24 * HOUR)).toBe('Refreshed 1d ago');
  expect(ago(50 * HOUR)).toBe('Refreshed 2d ago');
});

test('under a minute, or a finish the browser clock says is in the future, is just now', () => {
  const ago = (ms) => describeFreshness(NOW, finishedAgo(ms)).text;
  expect(ago(30 * 1000)).toBe('Refreshed just now');
  // A browser clock a few minutes behind the database's: never "-4m ago".
  expect(ago(-4 * 60 * 1000)).toBe('Refreshed just now');
});
