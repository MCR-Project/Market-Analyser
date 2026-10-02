// What the launch screen (components/layout/BackendGate.jsx) shows, as a
// function of how long the backend has been silent.
//
// Three phases rather than "waiting or not", because the same wait means
// different things at different lengths:
//
// - `quiet`: under QUIET_MS. A warm backend answers /health in well under
//   this, so showing a screen at all would only be a flash before the app.
//   Nothing is drawn but the page background.
// - `waking`: a backend that went to sleep on Render's free plan takes about
//   a minute to start. This is the case the screen is for, and it says so.
// - `slow`: past SLOW_MS the "it will be a minute" explanation has stopped
//   being true. The screen keeps trying but stops promising, and points at
//   what else makes a backend look unreachable: a wrong CORS_ORIGINS or
//   VITE_API_BASE is indistinguishable from a sleeping server in the browser
//   (README, "Deploying on Render"), as is a local backend that was never
//   started.

export const QUIET_MS = 400;
export const SLOW_MS = 90_000;

/** The phase for a backend that has not answered in `waitedMs`. */
export function launchPhase(waitedMs) {
  if (waitedMs < QUIET_MS) return 'quiet';
  if (waitedMs < SLOW_MS) return 'waking';
  return 'slow';
}
