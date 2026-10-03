import { test, expect } from 'vitest';
import {
  deepFillControl,
  deepFillPhase,
  chipLabel,
  controlCaption,
  readyNote,
  deepFillDialog,
  describeActionError,
  formatDuration,
  formatMoment,
  nextStatusPoll,
} from './deepFill';

// The shape GET /api/deep-fill/{id} answers, with only what a test changes.
function status(overrides = {}) {
  return {
    etfId: 'SPY',
    enabled: true,
    ttlSeconds: 86400,
    state: 'idle',
    untracked: { count: 457, weight: 52.3, weightShare: 52.3 },
    progress: null,
    cancelRequested: false,
    error: null,
    asOf: null,
    expiresAt: null,
    running: null,
    ...overrides,
  };
}

const running = (done, total, extra = {}) =>
  status({ state: 'running', progress: { done, total, failed: [] }, ...extra });

const ready = (extra = {}) =>
  status({
    state: 'ready',
    asOf: '2026-10-02T09:30:00+00:00',
    expiresAt: '2026-10-03T09:30:00+00:00',
    progress: { done: 457, total: 457, failed: [] },
    ...extra,
  });

// ── Which state the control is in ────────────────────────────────────────────

test('nothing to show until the status has arrived', () => {
  expect(deepFillControl(null).kind).toBe('hidden');
  expect(deepFillControl(undefined).kind).toBe('hidden');
});

test('a fund with no Untracked holdings has no control', () => {
  const s = status({ untracked: { count: 0, weight: 0, weightShare: null } });
  expect(deepFillControl(s).kind).toBe('hidden');
});

test('an idle fund with Untracked holdings offers to start', () => {
  expect(deepFillControl(status()).kind).toBe('start');
});

test('a version with Deep-fill off still shows the control, as disabled', () => {
  expect(deepFillControl(status({ enabled: false })).kind).toBe('disabled');
});

test('a running job is running, and says how far it has got', () => {
  const control = deepFillControl(running(212, 457));
  expect(control).toMatchObject({ kind: 'running', done: 212, total: 457 });
});

test('a finished Deep-fill is ready, until the status says otherwise', () => {
  expect(deepFillControl(ready()).kind).toBe('ready');
});

test('a result that has expired reads as idle again: the button returns', () => {
  const expired = status({ state: 'idle', asOf: null, expiresAt: null });
  expect(deepFillControl(expired).kind).toBe('start');
});

test("another fund's job holds the one slot: this fund cannot start", () => {
  const s = status({ running: { etfId: 'QQQ', done: 10, total: 90 } });
  expect(deepFillControl(s)).toMatchObject({ kind: 'busy', other: { etfId: 'QQQ', done: 10, total: 90 } });
});

test('a cancelled or failed job that kept something resumes rather than starts', () => {
  const cancelled = status({ state: 'cancelled', progress: { done: 150, total: 457, failed: [] } });
  expect(deepFillControl(cancelled)).toMatchObject({ kind: 'resume', done: 150, total: 457 });
  const failed = status({ state: 'failed', error: 'down', progress: { done: 100, total: 457, failed: [] } });
  expect(deepFillControl(failed).kind).toBe('resume');
});

test('a cancelled job that fetched nothing starts from the top', () => {
  const s = status({ state: 'cancelled', progress: { done: 0, total: 457, failed: [] } });
  expect(deepFillControl(s).kind).toBe('start');
});

test('a fund that is ready is not hidden for having a smaller tail than before', () => {
  expect(deepFillControl(ready({ untracked: { count: 0, weight: 0, weightShare: null } })).kind).toBe('ready');
});

// ── The phase and the chip ───────────────────────────────────────────────────

test('the phase is fetching while tickers are outstanding', () => {
  expect(deepFillPhase(running(212, 457))).toBe('fetching');
});

test('the phase is finishing when every ticker is in but the job has not ended', () => {
  expect(deepFillPhase(running(457, 457))).toBe('finishing');
});

test('a pending cancel is stopping, whatever else is true', () => {
  expect(deepFillPhase(running(212, 457, { cancelRequested: true }))).toBe('stopping');
  expect(deepFillPhase(running(457, 457, { cancelRequested: true }))).toBe('stopping');
});

test('the chip names the progress', () => {
  expect(chipLabel(running(212, 457))).toBe('Deep-filling 212/457');
});

// ── The caption beside the button ────────────────────────────────────────────
//
// Every state that has a button gets a caption, and each is computed from only
// the fields its own state has: a lookup table built from all of them at once
// read `other` on an idle fund and took the page down.

test('every state that offers a button has a caption, and none throws for lacking fields of another state', () => {
  const states = {
    start: status(),
    resume: status({ state: 'cancelled', progress: { done: 150, total: 457, failed: [] } }),
    disabled: status({ enabled: false }),
    busy: status({ running: { etfId: 'QQQ', done: 10, total: 90 } }),
  };
  for (const [kind, s] of Object.entries(states)) {
    expect(deepFillControl(s).kind).toBe(kind);
    expect(() => controlCaption(s)).not.toThrow();
    expect(typeof controlCaption(s)).toBe('string');
  }
});

test('the captions say what is true of that state', () => {
  expect(controlCaption(status())).toBe('457 untracked holdings');
  expect(controlCaption(status({ untracked: { count: 1, weight: 0.5, weightShare: 0.1 } }))).toBe('1 untracked holding');
  expect(controlCaption(status({ state: 'cancelled', progress: { done: 150, total: 457, failed: [] } }))).toBe('150 of 457 fetched');
  expect(controlCaption(status({ enabled: false }))).toBe('disabled on this version');
  expect(controlCaption(status({ running: { etfId: 'QQQ', done: 10, total: 90 } }))).toBe('QQQ is being filled');
});

test('a state with no button has no caption', () => {
  expect(controlCaption(running(1, 457))).toBeNull();
  expect(controlCaption(ready())).toBeNull();
  expect(controlCaption(null)).toBeNull();
});

// ── The ready note ───────────────────────────────────────────────────────────

test('the ready note says as of when, in the reader\'s own zone', () => {
  const note = readyNote(ready(), { locale: 'en-GB', timeZone: 'UTC' });
  expect(note).toBe('Full fund as of 2 Oct 2026, 09:30');
});

// ── The dialog's wording ─────────────────────────────────────────────────────

const text = (dialog) => dialog.body.join(' ');

test('the start dialog states the size, the time, that nothing is saved, the keep time and the container', () => {
  const dialog = deepFillDialog(status());
  const words = text(dialog);

  expect(words).toContain('457 holdings');
  expect(words).toContain('52.3% of the fund');
  expect(words).toContain('several minutes to tens of minutes');
  expect(words).toContain('longer on a small server');
  expect(words).toContain('Nothing is saved to the database');
  expect(words).toContain('24 hours');
  expect(words).toContain('containerised version');
  expect(dialog.actions).toEqual([
    { id: 'start', label: 'Start', primary: true },
    { id: 'close', label: 'Cancel' },
  ]);
});

test('the keep time follows what the server says, not a constant', () => {
  expect(text(deepFillDialog(status({ ttlSeconds: 7200 })))).toContain('2 hours');
});

test('a share that is not known is left out rather than guessed', () => {
  const s = status({ untracked: { count: 457, weight: 52.3, weightShare: null } });
  expect(text(deepFillDialog(s))).not.toContain('% of the fund');
});

test('the disabled dialog gives the instruction and offers no way to start', () => {
  const dialog = deepFillDialog(status({ enabled: false }));

  expect(text(dialog)).toContain(
    'Deep-filling is disabled on this version. To enable it, set `ALLOW_DEEP_FILL` in the project configuration'
  );
  expect(dialog.actions.map(a => a.id)).toEqual(['close']);
});

test('the running dialog shows the phase and the count, and offers to cancel the job', () => {
  const dialog = deepFillDialog(running(212, 457));

  expect(dialog.progress).toEqual({ phase: 'Fetching prices', done: 212, total: 457 });
  expect(text(dialog)).toContain('Closing this window leaves it running');
  expect(dialog.actions).toEqual([
    { id: 'cancel', label: 'Cancel Deep-fill' },
    { id: 'close', label: 'Close', primary: true },
  ]);
});

test('a job that has been asked to stop cannot be asked again', () => {
  const dialog = deepFillDialog(running(212, 457, { cancelRequested: true }));
  expect(dialog.progress.phase).toBe('Stopping after this batch');
  expect(dialog.actions.map(a => a.id)).toEqual(['close']);
});

test('the busy dialog names the other fund and its progress, with no start', () => {
  const dialog = deepFillDialog(status({ running: { etfId: 'QQQ', done: 10, total: 90 } }));
  expect(text(dialog)).toContain('QQQ');
  expect(text(dialog)).toContain('10/90');
  expect(dialog.actions.map(a => a.id)).toEqual(['close']);
});

test('the resume dialog says what was kept and offers to carry on', () => {
  const s = status({ state: 'cancelled', progress: { done: 150, total: 457, failed: [] } });
  const dialog = deepFillDialog(s);
  expect(text(dialog)).toContain('150 of 457');
  expect(dialog.actions[0]).toEqual({ id: 'start', label: 'Resume', primary: true });
});

test('a failed run says why, and what it kept', () => {
  const s = status({ state: 'failed', error: 'no Untracked holding could be fetched', progress: { done: 100, total: 457, failed: [] } });
  const words = text(deepFillDialog(s));
  expect(words).toContain('no Untracked holding could be fetched');
  expect(words).toContain('100 of 457');
});

test('the ready dialog names how many holdings could not be fetched, and when it expires', () => {
  const s = ready({
    progress: { done: 457, total: 457, failed: [{ ticker: 'ZZZ', reason: 'no price history' }, { ticker: 'YYY', reason: 'delisted' }] },
  });
  const dialog = deepFillDialog(s, { locale: 'en-GB', timeZone: 'UTC' });

  expect(text(dialog)).toContain('2 holdings could not be fetched');
  expect(text(dialog)).toContain('3 Oct 2026, 09:30');
  expect(dialog.failures).toEqual([
    { ticker: 'ZZZ', reason: 'no price history' },
    { ticker: 'YYY', reason: 'delisted' },
  ]);
  expect(dialog.actions.map(a => a.id)).toEqual(['close']);
});

test('a clean ready dialog does not mention failures', () => {
  expect(text(deepFillDialog(ready()))).not.toContain('could not be fetched');
});

// ── Why a press did not work ─────────────────────────────────────────────────

test('a 403 says Deep-fill is off, a 409 that another fund is running, a 400 that the fund cannot be filled', () => {
  expect(describeActionError({ status: 403 })).toContain('disabled');
  expect(describeActionError({ status: 409 })).toContain('another fund');
  expect(describeActionError({ status: 400 })).toContain('cannot be deep-filled');
});

test('a failure that will clear says to try again; a network failure says the server could not be reached', () => {
  expect(describeActionError({ status: 503 })).toContain('try again');
  expect(describeActionError(new TypeError('Failed to fetch'))).toContain('could not be reached');
});

// ── When to ask again ────────────────────────────────────────────────────────

test('a running job is polled every couple of seconds', () => {
  expect(nextStatusPoll(running(1, 457), 0)).toBe(2000);
});

test("waiting on another fund's job is polled, more slowly, so the button frees itself", () => {
  const s = status({ running: { etfId: 'QQQ', done: 10, total: 90 } });
  expect(nextStatusPoll(s, 0)).toBe(5000);
});

test("a fund with nothing untracked does not poll for another fund's job: it shows nothing to free", () => {
  const s = status({
    untracked: { count: 0, weight: 0, weightShare: null },
    running: { etfId: 'QQQ', done: 10, total: 90 },
  });
  expect(nextStatusPoll(s, 0)).toBeNull();
});

test('a ready fund is asked about again just after it should expire', () => {
  const now = Date.parse('2026-10-02T09:30:00+00:00');
  const hourBefore = now + 23 * 3600 * 1000;
  expect(nextStatusPoll(ready(), now)).toBe(24 * 3600 * 1000 + 1000);
  expect(nextStatusPoll(ready(), hourBefore)).toBe(3600 * 1000 + 1000);
});

test('a clock that thinks the result already expired does not hammer the server', () => {
  const afterExpiry = Date.parse('2026-10-05T00:00:00+00:00');
  expect(nextStatusPoll(ready(), afterExpiry)).toBe(5000);
});

test('the wait never exceeds what a timer can hold', () => {
  const far = ready({ expiresAt: '2099-01-01T00:00:00+00:00' });
  expect(nextStatusPoll(far, 0)).toBe(2147483647);
});

test('nothing is polled when nothing is moving', () => {
  expect(nextStatusPoll(status(), 0)).toBeNull();
  expect(nextStatusPoll(null, 0)).toBeNull();
  expect(nextStatusPoll(status({ state: 'cancelled' }), 0)).toBeNull();
});

// ── Plain words for durations and moments ────────────────────────────────────

test('durations read in the largest plain unit', () => {
  expect(formatDuration(86400)).toBe('24 hours');
  expect(formatDuration(3600)).toBe('1 hour');
  expect(formatDuration(5400)).toBe('90 minutes');
  expect(formatDuration(60)).toBe('1 minute');
  expect(formatDuration(30)).toBe('1 minute');
  expect(formatDuration(3 * 86400)).toBe('3 days');
});

test('midnight is 00:xx, not 24:xx, in a locale whose 24-hour clock says 24', () => {
  const moment = formatMoment('2026-10-03T00:05:00+00:00', { locale: 'en-US', timeZone: 'UTC' });
  expect(moment).toContain('00:05');
  expect(moment).not.toContain('24:05');
});

test('a keep time the server did not give is left out, not printed as NaN', () => {
  for (const ttlSeconds of [undefined, null, NaN, 0]) {
    const words = text(deepFillDialog(status({ ttlSeconds })));
    expect(words).not.toContain('NaN');
    expect(words).not.toContain('kept in memory for');
    expect(words).toContain('Nothing is saved to the database');
  }
});

test('a moment that does not parse is not invented', () => {
  expect(formatMoment('not a date')).toBeNull();
  expect(formatMoment(null)).toBeNull();
});
