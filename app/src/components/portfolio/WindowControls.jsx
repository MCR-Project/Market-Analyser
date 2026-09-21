/**
 * WindowControls — the stretch of history the portfolio is valued over.
 *
 * Presets answer "the last five years"; the two date fields answer "from
 * the 2020 crash to the end of 2021". Both write the same window, so
 * choosing a preset fills the dates and editing a date drops the preset —
 * there is one window, described two ways, and never two that disagree.
 *
 * Each date field is a text box with a calendar (`WindowDateField`, issue
 * #156), and both routes into it end at `editWindow`, which decides what one
 * date does to the window: send it (`commit`), keep it until the other bound
 * exists (`hold`), or say why it cannot be one (`problem`). Only the edited
 * bound ever changes, so changing one date never disturbs the other. A date is
 * only sent once it is a usable window, and an unusable one is said here, next
 * to the boxes, and nothing is asked of the server.
 *
 * Text is applied when it is finished — Enter or leaving the box — not while
 * it is being typed, which is what made typing a year unreliable before. What
 * is typed but not yet applied is `typed`; a date accepted while the other
 * bound is still missing (Max before its first run) is `held`. Both are dropped
 * the moment the window in force changes, however that happened, so a stale
 * half-answer never outlives the window it was about.
 *
 * **Max** is the one preset with no dates of its own: how far back a
 * basket reaches is a fact about its holdings. It asks the backend for
 * everything and reports the window that came back, which is why the
 * boundary is shown rather than assumed.
 *
 * Dragging across the chart writes here too (#65), which is why Reset
 * exists: a drag is easy to do by accident and fiddly to undo by hand,
 * so the window it replaced is kept until the window is chosen some
 * other way.
 */
import { useState } from 'react';
import { editWindow, today } from '../../utils/windowCalendar';
import { PRESETS } from '../../utils/windowPresets';
import { WindowDateField } from './WindowDateField';

export function WindowControls({
  preset,
  start,
  end,
  resolvedStart,
  resolvedEnd,
  onSelectPreset,
  onSetWindow,
  canReset,
  onReset,
}) {
  // The window in force, including the dates Max turned out to be: the fields
  // show these, and a preset or a drag replaces them.
  const inForce = `${preset}|${start}|${end}|${resolvedStart}|${resolvedEnd}`;
  const [typed, setTyped] = useState({ start: null, end: null });
  const [held, setHeld] = useState(null);
  const [problem, setProblem] = useState(null);

  // Whatever the window in force changes to invalidates half-finished input,
  // whichever control changed it. Adjusted during render, not in an effect: an
  // effect would paint the old text for a frame first.
  const clearInput = () => {
    setTyped({ start: null, end: null });
    setHeld(null);
    setProblem(null);
  };
  const [seen, setSeen] = useState(inForce);
  if (seen !== inForce) {
    setSeen(inForce);
    clearInput();
  }

  // Null means "showing whatever the window resolved to".
  const current = held ?? {
    start: start ?? resolvedStart ?? '',
    end: end ?? resolvedEnd ?? '',
  };
  const now = today();
  const missing = held ? (!held.start ? 'start' : !held.end ? 'end' : null) : null;

  const apply = (field, text) => {
    // Leaving a box nobody typed in, or typing back what was there, is not an
    // edit — and must not be answered as one.
    if (text.trim() === (current[field] ?? '')) {
      setTyped(t => ({ ...t, [field]: null }));
      setProblem(p => (p?.field === field ? null : p));
      return 'unchanged';
    }
    const result = editWindow(current, field, text, now);
    if (result.status === 'commit') {
      onSetWindow(result.window);
    } else if (result.status === 'hold') {
      setHeld(result.draft);
      setTyped(t => ({ ...t, [field]: null }));
      setProblem(null);
    } else {
      setProblem({ field, message: result.message });
    }
    return result.status;
  };

  const choose = (key) => {
    clearInput();
    onSelectPreset(key);
  };

  const dateField = (name, label, align) => (
    <WindowDateField
      field={name}
      label={label}
      value={typed[name] ?? current[name] ?? ''}
      bounds={current}
      today={now}
      hasProblem={problem?.field === name}
      align={align}
      onType={text => setTyped(t => ({ ...t, [name]: text }))}
      onApply={text => apply(name, text)}
    />
  );

  return (
    <div className="mb-5">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="eyebrow mb-1.5">WINDOW</div>
          <div className="inline-flex p-[3px] bg-[var(--bg-3)] rounded-[var(--radius-md)] gap-[1px]">
            {PRESETS.map(option => {
              const active = preset === option.key;
              return (
                <button
                  key={option.key}
                  onClick={() => choose(option.key)}
                  aria-pressed={active}
                  className="px-2.5 py-[5px] border-none rounded-[7px] cursor-pointer font-[var(--font-mono)] text-xs transition-all duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                  style={{
                    fontWeight: active ? 700 : 500,
                    background: active ? 'var(--bg-1)' : 'transparent',
                    color: active ? 'var(--fg)' : 'var(--fg-2)',
                    boxShadow: active ? 'var(--shadow-xs)' : 'none',
                  }}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        </div>

        {canReset && (
          <button
            onClick={onReset}
            className="h-[30px] px-3 text-[12px] font-semibold text-[var(--fg-1)] bg-[var(--bg-2)] border border-[var(--border)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-3)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
            title="Back to the window in force before the drag"
          >
            Reset
          </button>
        )}

        <div className="flex items-end gap-2">
          {dateField('start', 'FROM', 'left')}
          {dateField('end', 'TO', 'right')}
        </div>
      </div>

      {problem && (
        <p role="alert" className="text-[12px] text-[var(--warning)] leading-relaxed m-0 mt-2">
          {problem.message} Nothing has been re-simulated.
        </p>
      )}

      {!problem && missing && (
        <p className="text-[12px] text-[var(--fg-2)] leading-relaxed m-0 mt-2">
          Now the {missing} date. Nothing is re-simulated until there are two.
        </p>
      )}

      {!problem && !missing && preset === 'max' && resolvedStart && (
        <p className="text-[12px] text-[var(--fg-2)] leading-relaxed m-0 mt-2">
          As far back as this portfolio goes:{' '}
          <span className="font-[var(--font-mono)]">{resolvedStart}</span> is the earliest
          date any of its holdings has a price here.
        </p>
      )}
    </div>
  );
}
