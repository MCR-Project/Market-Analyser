/**
 * freshness — decides what the header's Freshness indicator says (issue #154).
 * Pure: no storage, no network, no DOM, no clock of its own — the caller hands
 * in `now`, which is what lets its rules be pinned by tests rather than by
 * waiting for a deadline to pass.
 *
 * The record is what `GET /api/freshness` answers: `{ finishedAt, dueBy,
 * failed }`, when the daily fetch job last finished, the moment after which no
 * newer run means the data is behind, and how many ids that run could not
 * refresh. The backend names the deadline and this compares it with the
 * browser's clock, so no calendar or schedule logic lives here — a weekend is
 * just a `dueBy` on Tuesday morning.
 *
 * Four states, in this order of precedence:
 *
 * - **unknown** — there is no usable record: Supabase is not configured, or no
 *   run has been recorded yet (a 200 of nulls), or the request failed, or is
 *   not being made. Never read as behind, and never as a date: a missing
 *   figure is absence, not a verdict. A record missing any one of its three
 *   fields is unknown too — a null failure count is not "nothing failed".
 * - **behind** — `now` has reached `dueBy` with no newer run. Says the data is
 *   from an old fetch, not that the job failed: a run that never started and
 *   one that crashed look the same. It outranks failures, since an overdue
 *   refresh makes the last run's failure count old news.
 * - **failures** — the last run finished on time but could not refresh `failed`
 *   ids, so some of the data is from an older fetch than the rest.
 * - **onSchedule** — none of the above.
 *
 * This is about the job, not the market: a market holiday adds no prices and the
 * job still ran, so the data is as fresh as any other day. It says nothing
 * about the date of the latest close, and the header says so in its tooltip.
 */

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** The parsed record, or null when there is nothing usable to judge. */
function readRecord(record) {
  if (!record) return null;
  const { finishedAt, dueBy, failed } = record;
  if (finishedAt == null || dueBy == null || failed == null) return null;
  const finished = Date.parse(finishedAt);
  const due = Date.parse(dueBy);
  if (Number.isNaN(finished) || Number.isNaN(due)) return null;
  return { finished, due, failed };
}

/**
 * Which state the data is in at `now` (milliseconds since the epoch).
 * @returns {'unknown' | 'behind' | 'failures' | 'onSchedule'}
 */
export function freshnessState(now, record) {
  const read = readRecord(record);
  if (!read) return 'unknown';
  if (now >= read.due) return 'behind';
  return read.failed > 0 ? 'failures' : 'onSchedule';
}

/**
 * How long before `now` a moment was: minutes under an hour, hours under a
 * day, days after. Under a minute — or a moment the browser's clock says is
 * still to come, when it runs a little behind the database's — is "just now",
 * never a negative age.
 */
function ago(now, then) {
  const elapsed = now - then;
  if (elapsed < MINUTE) return 'just now';
  if (elapsed < HOUR) return `${Math.floor(elapsed / MINUTE)}m ago`;
  if (elapsed < DAY) return `${Math.floor(elapsed / HOUR)}h ago`;
  return `${Math.floor(elapsed / DAY)}d ago`;
}

/**
 * The state and the words the header shows for it.
 * @returns {{ state: 'unknown' | 'behind' | 'failures' | 'onSchedule', text: string }}
 */
export function describeFreshness(now, record) {
  const state = freshnessState(now, record);
  if (state === 'unknown') return { state, text: 'Refresh status unknown' };

  const age = ago(now, Date.parse(record.finishedAt));
  if (state === 'behind') return { state, text: `Refresh overdue · last ${age}` };
  if (state === 'failures') return { state, text: `Refreshed ${age} · ${record.failed} failed` };
  return { state, text: `Refreshed ${age}` };
}
