/**
 * Whether what a fund-level read returned is still the answer (issue #172).
 *
 * A Deep-fill changes what the backend answers for a fund - the holdings list,
 * the correlation matrix, the sectors, the fund metrics, every measurement - and
 * so does its expiry, which changes them all back. None of those requests has a
 * parameter that says so, and each is made by its own hook, so nothing would
 * ask again. This holds one number per fund that moves exactly when the fund's
 * deep-filled state does, and those hooks put it in their dependencies
 * (`useDeepFillEpoch`).
 *
 * "Moves when the state does" is read off `asOf`, the instant the result was
 * drawn, which is null whenever the fund is not deep-filled:
 *
 *   null -> a time      a Deep-fill finished
 *   a time -> null      it expired
 *   a time -> another   it was redone between two looks
 *
 * The **first** thing seen for a fund is the baseline and does not move the
 * number, because the page's own requests already got the answer that was true
 * then: moving it would refetch the whole fund the moment the status arrived.
 * Nothing moves while a job is merely running - a partial tail changes nothing
 * anyone reads (the backend lays a tail over a fund only once its result
 * exists).
 *
 * Module state rather than component state, like `candlePreference`, because
 * the thing that observes (the page, polling the status) and the things that
 * read (hooks in five other components) share no parent that is not also the
 * page.
 */

// etfId -> { asOf, epoch }
const funds = new Map();
const listeners = new Set();

/** Record the `asOf` the status last said for a fund (null when not deep-filled). */
export function observeDeepFill(etfId, asOf) {
  const next = asOf ?? null;
  const known = funds.get(etfId);
  if (!known) {
    funds.set(etfId, { asOf: next, epoch: 0 });
    return;
  }
  if (known.asOf === next) return;
  funds.set(etfId, { asOf: next, epoch: known.epoch + 1 });
  listeners.forEach((listener) => listener());
}

/**
 * Drop what is known about a fund, for when the page stops watching it (the
 * hook unmounts or the fund changes). The baseline would otherwise go stale
 * while the user is elsewhere - a result that expired meanwhile makes the first
 * status on return look like a change, when the page's own requests on return
 * already read the new state - and a spurious move refetches the whole fund.
 */
export function forgetDeepFill(etfId) {
  funds.delete(etfId);
}

/** The fund's epoch: 0 until its deep-filled state has changed under the page. */
export function deepFillEpoch(etfId) {
  return funds.get(etfId)?.epoch ?? 0;
}

/** For `useSyncExternalStore`; returns the unsubscribe. */
export function subscribeDeepFill(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Forget everything. For tests. */
export function resetDeepFillEpochs() {
  funds.clear();
  listeners.clear();
}
