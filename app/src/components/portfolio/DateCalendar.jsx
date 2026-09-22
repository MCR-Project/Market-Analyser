/**
 * DateCalendar — the calendar a window's date field opens (issue #156).
 *
 * It edits **one** bound, the one whose field opened it, and knows nothing
 * about windows beyond that: it is handed the two bounds, the days that may be
 * picked (`range`, from `pickableRange`) and a callback. Days outside the range
 * are disabled rather than refused after the click, and the span between the
 * bounds is tinted, so a start is never chosen without seeing where the end is.
 *
 * Three views, one cursor. The day grid is the default; the title steps out to a
 * grid of years and then of months, so reaching 2008 is a few clicks and not
 * ninety-odd months of paging. The years and months offered are the ones with a
 * pickable day in them. The cursor (a date) is what all three move: a year or
 * month chosen keeps the day where it can, and the grid shows whichever month
 * the cursor is in, so a month arrow, Page Up and a typed date all agree about
 * what is on screen.
 *
 * Keyboard is the standard date grid, and lives in `moveFocus` where it is
 * tested: this file only focuses whichever day the cursor lands on. Only that
 * day is tabbable (a roving tabindex), so Tab leaves the grid instead of
 * walking forty-two buttons. Focus is never left on something that is about to
 * disappear: a year or month picked with the keyboard hands focus to the next
 * view, and a month arrow that reaches the edge of the range turns
 * `aria-disabled` rather than `disabled`, since a disabled button that holds
 * focus stops receiving keys — Escape included.
 *
 * `follow` is the date the field's text currently reads as, if it reads as one:
 * typing 2020-03-16 moves the calendar there while it is open.
 */
import { useEffect, useRef, useState } from 'react';
import {
  addDays,
  clampToRange,
  dateParts,
  isoDate,
  monthGrid,
  moveFocus,
  shiftMonth,
  utcDate,
} from '../../utils/windowCalendar';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];
const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];

/** "Monday, September 21, 2026" — what a screen reader says for a day, since
 *  the button itself only shows "21". */
const dayLabel = (iso) => utcDate(iso).toLocaleDateString('en-US', {
  weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC',
});

const focusRing = 'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--accent)]';
const plainButton = `border-none cursor-pointer font-[var(--font-mono)] transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-30 ${focusRing}`;

/** One year or month in the grids that step out from the days. */
function PickButton({ active, disabled, buttonRef, onClick, children }) {
  return (
    <button
      type="button"
      ref={buttonRef}
      disabled={disabled}
      onClick={onClick}
      className={`${plainButton} h-9 rounded-[var(--radius-sm)] text-xs hover:bg-[var(--bg-3)]`}
      style={{
        fontWeight: active ? 700 : 500,
        color: 'var(--fg)',
        background: active ? 'var(--accent-soft)' : 'transparent',
      }}
    >
      {children}
    </button>
  );
}

/** The month arrows. `aria-disabled`, not `disabled`: see the module note. */
function ArrowButton({ label, unavailable, onClick, children }) {
  return (
    <button
      type="button"
      onClick={() => { if (!unavailable) onClick(); }}
      aria-label={label}
      aria-disabled={unavailable}
      className={`${plainButton} h-7 w-7 rounded-[var(--radius-sm)] bg-transparent text-[var(--fg-1)] ${unavailable ? 'opacity-30 cursor-not-allowed' : 'hover:bg-[var(--bg-3)]'}`}
    >
      {children}
    </button>
  );
}

export function DateCalendar({ field, bounds, range, today, follow, focusToken, onPick }) {
  const value = bounds[field] || '';
  const otherBound = bounds[field === 'start' ? 'end' : 'start'] || '';

  const [mode, setMode] = useState('days');
  const [cursor, setCursor] = useState(() => clampToRange(value || today, range));

  // Follow what is typed. Adjusted during render rather than in an effect: an
  // effect would paint the old month for a frame first.
  const [seenFollow, setSeenFollow] = useState(follow);
  if (follow !== seenFollow) {
    setSeenFollow(follow);
    if (follow) setCursor(clampToRange(follow, range));
  }

  const cursorRef = useRef(null);
  const yearsBox = useRef(null);
  const currentPick = useRef(null);
  const focusAfterMove = useRef(false);
  const focusAfterView = useRef(false);

  // A key moved the cursor: the day it landed on is what keeps focus.
  useEffect(() => {
    if (!focusAfterMove.current) return;
    focusAfterMove.current = false;
    cursorRef.current?.focus();
  }, [cursor]);

  // The field asked for focus (ArrowDown in it): hand it to the cursor's day.
  useEffect(() => {
    if (focusToken > 0) cursorRef.current?.focus();
  }, [focusToken]);

  // A view changed. Open the year list on the year in force rather than at 1970
  // (scrolling the list itself, not the page, which `scrollIntoView` would also
  // move), and if a key made the change, give focus to what replaced the button
  // that had it.
  useEffect(() => {
    const box = yearsBox.current;
    const el = currentPick.current;
    if (mode === 'years' && box && el) box.scrollTop = el.offsetTop - box.clientHeight / 2 + el.clientHeight / 2;
    if (!focusAfterView.current) return;
    focusAfterView.current = false;
    (mode === 'days' ? cursorRef : currentPick).current?.focus();
  }, [mode]);

  const showView = (next, event) => {
    // A click made with Enter or Space has a `detail` of 0; a real one does not.
    focusAfterView.current = event.detail === 0;
    setMode(next);
  };

  const [cursorYear, cursorMonth] = dateParts(cursor);
  const monthStart = isoDate(cursorYear, cursorMonth, 1);
  const stepMonth = (delta) => setCursor(clampToRange(shiftMonth(cursor, delta), range));

  const onGridKeyDown = (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const next = moveFocus(cursor, e.key, range);
    if (!next) return;
    e.preventDefault();
    // A key that lands on the same day changes no state, so the effect above
    // would never clear the flag and would fire on some later, unrelated move.
    if (next === cursor) return;
    focusAfterMove.current = true;
    setCursor(next);
  };

  const [firstYear, lastYear] = [range.min, range.max].map(iso => dateParts(iso)[0]);
  const title = mode === 'days' ? `${MONTHS[cursorMonth - 1]} ${cursorYear}`
    : mode === 'months' ? String(cursorYear)
    : 'Choose a year';

  return (
    <div className="w-[256px] p-3 select-none">
      <div className="flex items-center justify-between gap-1 mb-2">
        <ArrowButton label="Previous month" unavailable={mode !== 'days' || monthStart <= range.min} onClick={() => stepMonth(-1)}>
          ‹
        </ArrowButton>
        <button
          type="button"
          onClick={e => showView(mode === 'years' ? 'days' : 'years', e)}
          aria-label={mode === 'years' ? 'Back to the days' : 'Choose the month and year'}
          className={`${plainButton} flex-1 h-7 rounded-[var(--radius-sm)] bg-transparent text-[12.5px] font-semibold text-[var(--fg)] hover:bg-[var(--bg-3)]`}
        >
          {title}
        </button>
        <ArrowButton label="Next month" unavailable={mode !== 'days' || shiftMonth(monthStart, 1) > range.max} onClick={() => stepMonth(1)}>
          ›
        </ArrowButton>
      </div>

      {mode === 'days' && (
        <table role="grid" aria-label={title} onKeyDown={onGridKeyDown} className="border-collapse">
          <thead>
            <tr>
              {WEEKDAYS.map(day => (
                <th key={day} scope="col" className="eyebrow h-6 w-8 p-0 font-normal">{day}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {monthGrid(cursorYear, cursorMonth).map(week => (
              <tr key={week[0].iso}>
                {week.map(({ iso, inMonth }) => {
                  const selected = iso === value;
                  const inSpan = bounds.start && bounds.end && iso > bounds.start && iso < bounds.end;
                  return (
                    <td key={iso} role="gridcell" aria-selected={selected} className="p-0">
                      <button
                        type="button"
                        ref={iso === cursor ? cursorRef : undefined}
                        tabIndex={iso === cursor ? 0 : -1}
                        disabled={iso < range.min || iso > range.max}
                        onClick={() => onPick(iso)}
                        aria-label={dayLabel(iso)}
                        aria-current={iso === today ? 'date' : undefined}
                        className={`${plainButton} h-8 w-8 rounded-[var(--radius-sm)] text-xs hover:bg-[var(--bg-3)]`}
                        style={{
                          fontWeight: selected ? 700 : 500,
                          color: selected ? 'var(--accent-fg)' : inMonth ? 'var(--fg)' : 'var(--fg-3)',
                          background: selected ? 'var(--accent)' : inSpan || iso === otherBound ? 'var(--accent-soft)' : 'transparent',
                          boxShadow: iso === today ? 'inset 0 0 0 1px var(--border-strong)' : 'none',
                          // Square, so the days between the bounds read as one band
                          // instead of a row of rounded tiles with gaps at the corners.
                          borderRadius: inSpan ? 0 : undefined,
                        }}
                      >
                        {Number(iso.slice(8))}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {mode === 'months' && (
        <div className="grid grid-cols-3 gap-1">
          {MONTHS.map((name, index) => {
            const first = isoDate(cursorYear, index + 1, 1);
            return (
              <PickButton
                key={name}
                active={index + 1 === cursorMonth}
                buttonRef={index + 1 === cursorMonth ? currentPick : undefined}
                disabled={addDays(shiftMonth(first, 1), -1) < range.min || first > range.max}
                onClick={e => {
                  setCursor(clampToRange(shiftMonth(cursor, index + 1 - cursorMonth), range));
                  showView('days', e);
                }}
              >
                {name.slice(0, 3)}
              </PickButton>
            );
          })}
        </div>
      )}

      {mode === 'years' && (
        <div ref={yearsBox} className="relative grid grid-cols-4 gap-1 max-h-[216px] overflow-y-auto">
          {Array.from({ length: lastYear - firstYear + 1 }, (_, i) => firstYear + i).map(year => (
            <PickButton
              key={year}
              active={year === cursorYear}
              buttonRef={year === cursorYear ? currentPick : undefined}
              onClick={e => {
                setCursor(clampToRange(shiftMonth(cursor, (year - cursorYear) * 12), range));
                showView('months', e);
              }}
            >
              {year}
            </PickButton>
          ))}
        </div>
      )}
    </div>
  );
}
