// Shared auto-retry schedule for a transient failure (see isTransientError
// in api.js). Used by both useFetch and useMeasurements, which otherwise
// hand-rolled the same flat "every 3 seconds, forever" rule independently
// (issue #92).
//
// A flat 3s interval was fine for the failure it was written for: a local
// cold start, where the backend binds its port before Yahoo/Supabase will
// answer it, and the gap closes in a few seconds. It is the wrong answer
// to a failure that can last a full minute - Yahoo rate-limiting the
// backend's shared cloud IP - because retrying every 3s for that whole
// minute is exactly the traffic that keeps the block in place. Doubling
// up to a cap lets both cases share one schedule without either guessing
// which failure this one is.

// After this many consecutive automatic retries, stop and leave the
// failure showing with its Retry button - at the schedule below that's
// roughly 3+6+12+24+48+60+60+60 = 273s, "about 4½ minutes" of trying on
// its own before it's someone's call to keep waiting.
export const MAX_AUTO_RETRIES = 8;

const BASE_DELAY_MS = 3000;
const MAX_DELAY_MS = 60000;

/**
 * The delay (ms) before the given automatic retry attempt (1-indexed:
 * the first auto-retry after a failure is attempt 1). Doubles from
 * BASE_DELAY_MS up to MAX_DELAY_MS, and never returns less than
 * `retryAfterMs` - the backend's own Retry-After (ApiError.retryAfter in
 * api.js) is a lower bound it actually measured, e.g. the remaining time
 * on a rate-limit cooldown, not a suggestion this schedule is free to
 * undercut.
 */
export function retryDelayMs(attempt, retryAfterMs = 0) {
  const scheduled = Math.min(BASE_DELAY_MS * 2 ** (attempt - 1), MAX_DELAY_MS);
  return Math.max(scheduled, retryAfterMs);
}
