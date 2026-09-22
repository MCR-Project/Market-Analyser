/**
 * WindowDateField — one of the window's two dates: a text box you can type in
 * and a calendar you can pick from (issue #156).
 *
 * Why a text box and not `<input type="date">`. The native control reports a
 * full, valid date at every step of typing a year (0002, 0020, 0202, 2020), and
 * the old code committed the first of them: a simulation per digit, and a box
 * that jumped under the cursor. Text is committed when it is *finished* —
 * Enter, or leaving the box — never while it is being typed, and it is pasteable
 * from a spreadsheet. The native control also drew differently in every browser
 * and ignored the theme.
 *
 * The box and the calendar are two ways of saying one thing, so neither owns
 * it: both hand a date to `onApply`, the parent decides what it does to the
 * window, and this file only decides how the popover opens and closes.
 *
 *   - clicking the box opens the calendar, and focus stays in the box so you
 *     can carry on typing while the calendar follows;
 *   - ArrowDown opens it *and* moves focus to its day grid, the way a
 *     combobox's list is entered — Left, Right, Home and End belong to the
 *     caret in a text box, so the grid's own keys need the grid to be focused;
 *   - Escape, leaving the field, and a committed date close it; Escape and a
 *     pick return focus to the box.
 *
 * The popover is not modal. Nothing behind it is disabled, so it does not go
 * through `Overlay`, whose focus trap would stop you tabbing back to the next
 * control.
 */
import { useId, useRef, useState } from 'react';
import { parseTypedDate, pickableRange } from '../../utils/windowCalendar';
import { DateCalendar } from './DateCalendar';

export function WindowDateField({
  field,
  label,
  value,
  bounds,
  today,
  hasProblem,
  align = 'left',
  onType,
  onApply,
}) {
  const [open, setOpen] = useState(false);
  const [focusToken, setFocusToken] = useState(0);
  const input = useRef(null);
  const root = useRef(null);
  const popoverId = useId();

  // Closing also forgets the request to focus the grid. Left at 1, the next
  // calendar — opened by a click, to type into — would mount, see a token above
  // zero and take focus from the box it was opened from.
  const close = () => {
    setOpen(false);
    setFocusToken(0);
  };

  const closeToInput = () => {
    close();
    input.current?.focus();
  };

  const pick = (iso) => {
    const status = onApply(iso);
    if (status !== 'problem') closeToInput();
  };

  return (
    <div
      ref={root}
      className="relative"
      onBlur={e => {
        if (!e.currentTarget.contains(e.relatedTarget)) close();
      }}
      onKeyDown={e => {
        if (e.key === 'Escape' && open) {
          e.preventDefault();
          e.stopPropagation();
          closeToInput();
        }
      }}
    >
      <label>
        <span className="eyebrow block mb-1.5">{label}</span>
        <input
          ref={input}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          spellCheck={false}
          placeholder="YYYY-MM-DD"
          value={value}
          aria-label={`Window ${field} date`}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={open ? popoverId : undefined}
          aria-invalid={hasProblem || undefined}
          onChange={e => onType(e.target.value)}
          onClick={() => setOpen(true)}
          // Focus going into the popover (ArrowDown) is not leaving the box: the
          // text is not finished, and answering it now would raise a warning about
          // half a date just because the calendar was asked for.
          onBlur={e => {
            if (!root.current?.contains(e.relatedTarget)) onApply(value);
          }}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              e.preventDefault();
              // A held or unchanged date is finished too; only a problem keeps the
              // calendar open, because the text still has to be put right.
              if (onApply(value) !== 'problem') close();
            } else if (e.key === 'ArrowDown' && !e.altKey && !e.ctrlKey && !e.metaKey) {
              e.preventDefault();
              setOpen(true);
              setFocusToken(token => token + 1);
            }
          }}
          className="h-[30px] w-[108px] px-2 bg-[var(--bg-1)] border rounded-[var(--radius-sm)] font-[var(--font-mono)] text-[12.5px] text-[var(--fg)] placeholder:text-[var(--fg-3)] outline-none focus:border-[var(--accent-ring)]"
          style={{ borderColor: hasProblem ? 'var(--warning-ring)' : 'var(--border)' }}
        />
      </label>

      {open && (
        <div
          id={popoverId}
          role="dialog"
          aria-label={`Choose the ${field} date`}
          // A press inside the popover must not take focus from the box, or the
          // box would blur and apply half-typed text before the click landed.
          onMouseDown={e => e.preventDefault()}
          className={`absolute top-full mt-1 z-30 bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-md)] shadow-[var(--shadow-md)] ${align === 'right' ? 'right-0' : 'left-0'}`}
        >
          <DateCalendar
            field={field}
            bounds={bounds}
            range={pickableRange(field, bounds, today)}
            today={today}
            follow={parseTypedDate(value)}
            focusToken={focusToken}
            onPick={pick}
          />
        </div>
      )}
    </div>
  );
}
