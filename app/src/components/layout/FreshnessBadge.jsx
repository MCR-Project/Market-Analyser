/**
 * FreshnessBadge — the header's answer to "is this data from a recent fetch?"
 * (issue #154). A dot and a phrase, both chosen by utils/freshness.js:
 *
 *   ● Refreshed 3h ago                  green — the last run finished on time
 *   ● Refreshed 3h ago · 4 failed       amber — on time, but some ids were not refreshed
 *   ● Refresh overdue · last 2d ago     red   — no newer run by its deadline
 *   ● Refresh status unknown            grey  — nothing readable to judge
 *
 * It is about the daily fetch job, not the market, and the tooltip says so: a
 * market holiday adds no new prices and the job still runs, so this is not the
 * date of the latest close. The same sentence is in a real `sr-only` span
 * beside the `title`, which is not reliably announced to a screen reader (the
 * convention MdxCell's `reason` follows).
 *
 * The dot shows at every width; only the phrase steps aside on a narrow window,
 * where it stays in the page for a screen reader. A warning must not vanish on
 * a phone just because the words no longer fit. It is its own element, beside
 * the LIVE badge rather than folded into it: that one is about connectivity and
 * only the dashboard publishes it.
 */
const DOT = {
  onSchedule: 'var(--color-success)',
  failures: 'var(--color-warning)',
  behind: 'var(--color-danger)',
  unknown: 'var(--fg-3)',
};

const NOT_THE_LATEST_CLOSE =
  'This is when the daily data job last finished, not the date of the latest price: market holidays add no new prices and the job still runs.';

function lastRunLine(finishedAt) {
  if (!finishedAt) return 'No record of the last run could be read.';
  const when = new Date(finishedAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  return `Last run finished ${when}.`;
}

export function FreshnessBadge({ freshness }) {
  const { state, text, finishedAt } = freshness;
  const explanation = `${lastRunLine(finishedAt)} ${NOT_THE_LATEST_CLOSE}`;

  return (
    <span
      title={`${text}\n${explanation}`}
      className="font-[var(--font-mono)] text-[11px] flex-none flex items-center gap-1.5 whitespace-nowrap"
      style={{ color: state === 'behind' ? 'var(--color-danger)' : 'var(--fg-2)' }}
    >
      <span aria-hidden="true" className="w-1.5 h-1.5 rounded-full" style={{ background: DOT[state] }} />
      <span className="sr-only md:not-sr-only">{text}</span>
      <span className="sr-only">. {explanation}</span>
    </span>
  );
}
