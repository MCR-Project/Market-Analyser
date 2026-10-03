/**
 * What the page says and offers about a fund's Deep-fill (issue #172).
 *
 * The backend decides everything that is a fact - whether the version allows it,
 * what is running, how far it has got, when a result expires (`GET
 * /api/deep-fill/{id}`, issue #171). This module decides only what the page
 * makes of that answer, and holds nothing: no storage, no network, no clock
 * (`now` is passed in), so every rule here is tested through its public function.
 *
 * A fund's control is in one of seven states, in this precedence:
 *
 *   hidden    nothing to offer: the status has not arrived, or the fund has no
 *             Untracked holdings (a fund that is *ready* is never hidden, so
 *             the note that says it is deep-filled cannot vanish)
 *   ready     the fund is deep-filled; the "full fund as of ..." note
 *   running   a job for this fund is fetching
 *   disabled  this version has Deep-fill off (`ALLOW_DEEP_FILL`); the button
 *             is still shown, because the dialog is where it says why
 *   busy      another fund's job holds the server's one slot
 *   resume    a cancelled or failed job kept some of the fund; pressing
 *             start fetches only the rest
 *   start     the plain case
 *
 * Words are plain on purpose: this is a warning about time and memory, and says
 * what a Deep-fill does *not* do (write to the database) as readily as what it
 * does.
 */

/** The longest delay a browser timer can hold; a longer one fires at once. */
const MAX_TIMER_MS = 2147483647;
/** How often a running job is asked about. */
const RUNNING_POLL_MS = 2000;
/** How often a fund waiting on another fund's job is asked about. */
const BUSY_POLL_MS = 5000;
/** The floor for the wait to an expiry, so a skewed clock cannot hammer the server. */
const MIN_EXPIRY_POLL_MS = 5000;

const PHASE_WORDS = {
  fetching: 'Fetching prices',
  finishing: 'Putting the fund together',
  stopping: 'Stopping after this batch',
};

/** Which state a fund's control is in. See the module comment for the order. */
export function deepFillControl(status) {
  if (!status) return { kind: 'hidden' };
  if (status.state === 'ready') {
    return { kind: 'ready', asOf: status.asOf, expiresAt: status.expiresAt };
  }
  if (!status.untracked || status.untracked.count === 0) return { kind: 'hidden' };

  if (status.state === 'running') {
    const { done, total } = status.progress ?? { done: 0, total: status.untracked.count };
    return { kind: 'running', done, total, phase: deepFillPhase(status) };
  }
  if (!status.enabled) return { kind: 'disabled' };
  if (status.running) return { kind: 'busy', other: status.running };

  const kept = status.progress?.done ?? 0;
  if ((status.state === 'cancelled' || status.state === 'failed') && kept > 0) {
    return { kind: 'resume', done: kept, total: status.progress.total };
  }
  return { kind: 'start' };
}

/**
 * Where a running job is: `fetching` while tickers are outstanding, `finishing`
 * once every one is in and the job is putting the fund's result together, and
 * `stopping` from the moment a cancel is pending - which wins, because the job
 * will not go on to the next batch whatever else is true.
 */
export function deepFillPhase(status) {
  if (status.cancelRequested) return 'stopping';
  const { done, total } = status.progress ?? { done: 0, total: 0 };
  return total > 0 && done >= total ? 'finishing' : 'fetching';
}

/** The chip on the fund card while a job runs. */
export function chipLabel(status) {
  const { done, total } = status.progress ?? { done: 0, total: 0 };
  return `Deep-filling ${done}/${total}`;
}

/** The note that replaces the button while the fund is deep-filled. */
export function readyNote(status, format) {
  const moment = formatMoment(status.asOf, format);
  return moment ? `Full fund as of ${moment}` : 'Full fund';
}

/**
 * How long until the status is worth asking for again, in ms, or null when
 * nothing is moving and the page should wait for a press or the tab returning.
 *
 * A running job is polled every couple of seconds. A fund waiting on another's
 * job is polled slowly, so its button frees itself when that ends. A ready fund
 * is asked about again just after it should expire - the backend checks expiry
 * on every read, so the answer then is the truth - but never sooner than 5s, so
 * a browser clock ahead of the server's cannot turn that into a tight loop.
 */
export function nextStatusPoll(status, now) {
  if (!status) return null;
  if (status.state === 'running') return RUNNING_POLL_MS;
  if (status.state === 'ready') {
    const expires = Date.parse(status.expiresAt);
    if (Number.isNaN(expires)) return null;
    return Math.min(MAX_TIMER_MS, Math.max(MIN_EXPIRY_POLL_MS, expires - now + 1000));
  }
  // Only worth asking while the button is there to free: a fund with nothing
  // untracked shows no control, whoever else is running a job.
  if (deepFillControl(status).kind === 'busy') return BUSY_POLL_MS;
  return null;
}

/**
 * The dialog for a fund's current state: `{ title, body, progress?, failures?,
 * actions }`. `body` is paragraphs of plain text, in which `code` between
 * backticks is a configuration name the dialog sets in monospace. `actions` are
 * ids the dialog maps to behaviour (`start`, `cancel`, `close`); a state that
 * cannot start anything has no `start` in it, which is how "disabled" and "busy"
 * stay unable to start a Deep-fill rather than merely discouraged from it.
 * `format` is `{ locale, timeZone }` for the dates, for tests.
 */
export function deepFillDialog(status, format) {
  const control = deepFillControl(status);
  const close = (primary = false) => ({ id: 'close', label: 'Close', ...(primary ? { primary } : {}) });

  switch (control.kind) {
    case 'disabled':
      return {
        title: 'Deep-fill',
        body: [
          'Deep-filling is disabled on this version. To enable it, set `ALLOW_DEEP_FILL` in the project configuration.',
        ],
        actions: [close()],
      };

    case 'busy':
      return {
        title: 'Deep-fill',
        body: [
          `A Deep-fill of ${control.other.etfId} is running (${control.other.done}/${control.other.total}). ` +
          'The server fills one fund at a time; come back to this one when that finishes.',
        ],
        actions: [close()],
      };

    case 'running': {
      const stopping = control.phase === 'stopping';
      return {
        title: 'Deep-fill',
        body: [
          'Closing this window leaves it running; the chip on the fund card shows how far it has got.',
          'Cancelling keeps what has been fetched, so starting again carries on from there.',
        ],
        progress: { phase: PHASE_WORDS[control.phase], done: control.done, total: control.total },
        actions: stopping
          ? [close(true)]
          : [{ id: 'cancel', label: 'Cancel Deep-fill' }, close(true)],
      };
    }

    case 'ready': {
      const expires = formatMoment(control.expiresAt, format);
      const failed = status.progress?.failed ?? [];
      const body = [
        `This fund is read as its whole basket, as of ${formatMoment(control.asOf, format) ?? 'the last fetch'}.` +
          (expires ? ` It is kept until ${expires}, then goes back to its tracked holdings.` : ''),
      ];
      if (failed.length > 0) {
        body.push(
          `${failed.length} ${failed.length === 1 ? 'holding' : 'holdings'} could not be fetched and ` +
          'are left out; their figures show a dash with the reason.'
        );
      }
      return {
        title: 'Deep-fill',
        body,
        failures: failed.map(({ ticker, reason }) => ({ ticker, reason })),
        actions: [close(true)],
      };
    }

    case 'resume':
    case 'start': {
      const { count, weightShare } = status.untracked;
      const share = weightShare == null ? '' : ` (${weightShare}% of the fund's weight)`;
      const body = [];
      if (control.kind === 'resume') {
        const lead = status.state === 'failed'
          ? `The last run stopped: ${status.error ?? 'the data source could not be reached'}.`
          : 'The last run was cancelled.';
        body.push(
          `${lead} It kept ${control.done} of ${control.total} holdings; starting again fetches only the rest.`
        );
      }
      body.push(
        `${count} ${count === 1 ? 'holding' : 'holdings'}${share} ${count === 1 ? 'is' : 'are'} untracked: ` +
          "this app stores no prices for them, so the fund's figures describe only the rest.",
        'A Deep-fill fetches their prices live. It takes several minutes to tens of minutes, longer on a small server.',
        // The keep time is the server's to say; a status without it (an older
        // backend) leaves the clause out rather than printing a made-up figure.
        'Nothing is saved to the database.' + (
          Number.isFinite(status.ttlSeconds) && status.ttlSeconds > 0
            ? ` The result is kept in memory for ${formatDuration(status.ttlSeconds)}, then the fund goes back to its tracked holdings.`
            : ' The fund goes back to its tracked holdings when the result expires.'
        ),
        'For a fund this size, run the containerised version (docker compose) rather than a small hosted server.',
      );
      return {
        title: 'Deep-fill',
        body,
        actions: [
          { id: 'start', label: control.kind === 'resume' ? 'Resume' : 'Start', primary: true },
          { id: 'close', label: 'Cancel' },
        ],
      };
    }

    default:
      return null;
  }
}

/**
 * Why a press of start or cancel did not work, in words. A refusal is a 4xx the
 * frontend never retries, so each says what to change instead of promising a
 * retry; only the 429/5xx/network failures that heal say to try again.
 */
export function describeActionError(err) {
  if (err instanceof TypeError) {
    return 'The server could not be reached. Check that the backend is running, then try again.';
  }
  switch (err?.status) {
    case 403: return 'Deep-filling is disabled on this version.';
    case 409: return 'A Deep-fill is already running for another fund.';
    case 400: return 'This fund cannot be deep-filled: it has nothing untracked left to fill, or more than this server can hold.';
    case 429: return 'Too many requests just now; wait a moment and try again.';
    case 503: return "The server could not read this fund's holdings just now; try again in a moment.";
    default: return 'The Deep-fill request failed. Try again.';
  }
}

function plural(n, unit) {
  return `${n} ${unit}${n === 1 ? '' : 's'}`;
}

/** `seconds` in the largest plain unit that says it exactly, rounding only when none does. */
export function formatDuration(seconds) {
  const hours = seconds / 3600;
  if (seconds >= 3600 && Number.isInteger(hours)) {
    return hours > 48 && hours % 24 === 0 ? plural(hours / 24, 'day') : plural(hours, 'hour');
  }
  if (seconds < 7200) return plural(Math.max(1, Math.round(seconds / 60)), 'minute');
  return hours > 48 ? plural(Math.round(hours / 24), 'day') : plural(Math.round(hours), 'hour');
}

/** An ISO instant as a short local date and time, or null if it is not one. */
export function formatMoment(iso, { locale, timeZone } = {}) {
  const date = new Date(iso ?? NaN);
  if (iso == null || Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
    // h23, not `hour12: false`: that picks h24 in some locales (en-US), which
    // writes midnight as 24:05.
    hourCycle: 'h23', timeZone,
  }).format(date);
}
