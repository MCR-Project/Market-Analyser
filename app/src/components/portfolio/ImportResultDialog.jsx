/**
 * ImportResultDialog — what an import did (issue #148).
 *
 * Shown after every import, and there is no confirmation before one:
 * importing only ever adds (ADR 0001), so there is nothing to ask about
 * beforehand, and without this a successful import would look like nothing
 * happened. It is the record.
 *
 * It shows only the groups that apply, in the order somebody wants them:
 * what was added, what had to be renamed, what was skipped because the
 * library already had exactly that, and what could not be imported and why.
 * A portfolio that was skipped is named rather than counted - "3 skipped"
 * would leave somebody unsure whether the one they were after was among
 * them.
 *
 * It also says when the browser would not keep what was added. A refused
 * write does not roll an import back (the session keeps working with what
 * it has), so "Added 3 portfolios" with nothing more would be a promise the
 * next reload breaks.
 *
 * Everything from the file is shown as text only: names and reasons come
 * from somebody's file and are never built into anything.
 */
import { Overlay } from '../ui/Overlay';
import { STORAGE_FULL, STORAGE_OK } from '../../store/portfolioStorage';

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function Group({ title, children }) {
  return (
    <section className="mb-4">
      <div className="text-[12px] font-bold text-[var(--fg-2)] mb-1.5">{title}</div>
      <ul className="list-none m-0 p-0 flex flex-col gap-1">{children}</ul>
    </section>
  );
}

function Item({ children }) {
  return <li className="text-[13px] leading-snug text-[var(--fg)] break-words">{children}</li>;
}

/** What to say when the write was refused, or null when it was not (or
 *  when there was nothing to write). */
function unsavedNotice(written) {
  if (written == null || written === STORAGE_OK) return null;
  return written === STORAGE_FULL
    ? 'Not saved to this browser: its storage is full. They are on screen for now, but will not survive a reload until there is room.'
    : 'Not saved to this browser: site data is unavailable here. They are on screen for now, and will be gone when the tab closes.';
}

export function ImportResultDialog({ result, onClose }) {
  const { plan, written } = result;
  const unsaved = unsavedNotice(written);

  let title;
  if (plan.error) title = 'This file could not be imported';
  else if (plan.added.length > 0) title = `Added ${plural(plan.added.length, 'portfolio', 'portfolios')}`;
  else title = 'Nothing new to import';

  return (
    <Overlay
      onClose={onClose}
      ariaLabel="Import result"
      className="fixed inset-0 z-80 flex items-start justify-center pt-[12vh] px-5 pb-5"
      style={{ background: 'color-mix(in oklab, var(--bg-inset) 70%, transparent)', backdropFilter: 'blur(3px)' }}
      contentClassName="w-full max-w-[480px] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] p-5 animate-[corrPop_var(--dur-fast)_var(--ease-out)]"
    >
      <div className="eyebrow mb-2">IMPORT</div>
      <p className="text-[14px] font-bold text-[var(--fg)] m-0 mb-3 leading-relaxed">{title}</p>

      {plan.error && (
        <p className="text-[13px] text-[var(--fg-1)] m-0 mb-4 leading-relaxed">{plan.error}</p>
      )}

      {unsaved && (
        <p
          role="status"
          className="text-[13px] text-[var(--fg-1)] m-0 mb-4 p-3 leading-relaxed rounded-[var(--radius-md)] border bg-[var(--warning-soft)] border-[var(--warning-ring)]"
        >
          {unsaved}
        </p>
      )}

      {!plan.error && plan.added.length === 0 && plan.skipped.length > 0 && (
        <p className="text-[13px] text-[var(--fg-2)] m-0 mb-4 leading-relaxed">
          Everything in this file is already in your library exactly as it is, so nothing was added.
        </p>
      )}

      <div className="corr-scroll max-h-[50vh] overflow-y-auto -mx-1 px-1">
        {plan.added.length > 0 && (
          <Group title={`Added (${plan.added.length})`}>
            {plan.added.map(portfolio => <Item key={portfolio.id}>{portfolio.name}</Item>)}
          </Group>
        )}

        {plan.renamed.length > 0 && (
          <Group title="Renamed, because the name was taken">
            {plan.renamed.map(({ from, to }) => (
              <Item key={to}>
                {from} <span className="text-[var(--fg-2)]">→</span> {to}
              </Item>
            ))}
          </Group>
        )}

        {plan.skipped.length > 0 && (
          <Group title={`Skipped — already in your library (${plan.skipped.length})`}>
            {plan.skipped.map((name, index) => <Item key={`${index}:${name}`}>{name}</Item>)}
          </Group>
        )}

        {plan.failed.length > 0 && (
          <Group title={`Could not be imported (${plan.failed.length})`}>
            {plan.failed.map(({ name, reason }, index) => (
              <Item key={`${index}:${name}`}>
                <strong className="font-semibold">{name}</strong>
                <span className="text-[var(--fg-2)]"> — {reason}</span>
              </Item>
            ))}
          </Group>
        )}
      </div>

      <div className="flex justify-end mt-2">
        <button
          onClick={onClose}
          className="px-3.5 py-2 text-[13px] font-semibold text-[var(--accent)] bg-[var(--accent-soft)] border border-[var(--accent-ring)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--accent-ring)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          Done
        </button>
      </div>
    </Overlay>
  );
}
