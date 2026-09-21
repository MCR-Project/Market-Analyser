/**
 * windowPresets — what each button on the window control means in dates
 * (issue #156, moved out of `useSimulationWindow` so it is a pure module and
 * takes the date as an argument instead of reading the clock).
 *
 * A preset is relative to today and stays relative — "the last year" means the
 * last year whenever the link is opened — and it counts on the **UTC** calendar,
 * the one `today()` and the backend's `end` check use. Mixing a local year or
 * local day with a UTC today is how YTD came to start after it ended for anybody
 * ahead of UTC around New Year.
 *
 * **Max** is the one preset with no dates of its own: how far back a basket
 * reaches is a fact about its holdings, so it travels to the backend as a period
 * and comes back as the window it turned out to be.
 */
import { today } from './windowCalendar';

/** Mirrors PERIOD_TO_DAYS in backend/config.py, so a preset asks for the
 *  same stretch the backend would have counted back itself. */
const DAYS = { '1m': 30, '3m': 90, '6m': 182, '1y': 365, '5y': 1825 };

/** In the order they are drawn: the plain spans, shortest to longest, then the
 *  two that are not one. YTD's length changes through the year and Max has no
 *  dates at all, so putting either among the spans would make the row read as
 *  a scale it is not. */
export const PRESETS = [
  { key: '1m', label: '1M' },
  { key: '3m', label: '3M' },
  { key: '6m', label: '6M' },
  { key: '1y', label: '1Y' },
  { key: '5y', label: '5Y' },
  { key: 'ytd', label: 'YTD' },
  { key: 'max', label: 'Max' },
];

export const DEFAULT_PRESET = '1y';

/** What a preset means in dates, as of `now`. An unknown key reads as the
 *  default's stretch, so a bad link still opens a window. */
export function presetWindow(key, now = new Date()) {
  if (key === 'max') return { period: 'max', start: null, end: null };
  if (key === 'ytd') return { start: `${now.getUTCFullYear()}-01-01`, end: today(now) };
  const days = DAYS[key] ?? DAYS[DEFAULT_PRESET];
  return { start: today(new Date(now.getTime() - days * 86_400_000)), end: today(now) };
}
