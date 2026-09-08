/**
 * WindowControls — the stretch of history the portfolio is valued over.
 *
 * Presets answer "the last five years"; the two date boxes answer "from
 * the 2020 crash to the end of 2021". Both write the same window, so
 * choosing a preset fills the dates and editing a date drops the preset —
 * there is one window, described two ways, and never two that disagree.
 *
 * A date is only sent once it is a usable window. A half-typed year is a
 * legitimate state of a date input, not a request worth making, and an end
 * before its start is a fact about the request that the backend would
 * answer 400 to — so both are said here, next to the boxes, and nothing is
 * asked of the server.
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
import { PRESETS, today, windowProblem } from '../../hooks/useSimulationWindow';

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
  // What is in the boxes, which is not the window until it makes sense as
  // one. Null means "showing whatever the window resolved to".
  const [draft, setDraft] = useState(null);

  const shown = draft ?? {
    start: start ?? resolvedStart ?? '',
    end: end ?? resolvedEnd ?? '',
  };
  const problem = draft ? windowProblem(draft) : null;

  const edit = (field, value) => {
    const next = { ...shown, [field]: value };
    setDraft(next);
    if (next.start && next.end && !windowProblem(next)) {
      onSetWindow(next);
      setDraft(null);
    }
  };

  const choose = (key) => {
    setDraft(null);
    onSelectPreset(key);
  };

  return (
    <div className="mb-5">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="eyebrow mb-1.5">PERIOD</div>
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
          <label>
            <span className="eyebrow block mb-1.5">FROM</span>
            <input
              type="date"
              value={shown.start}
              max={today()}
              onChange={e => edit('start', e.target.value)}
              aria-label="Window start date"
              className="h-[30px] px-2 bg-[var(--bg-1)] border rounded-[var(--radius-sm)] font-[var(--font-mono)] text-[12.5px] text-[var(--fg)] outline-none focus:border-[var(--accent-ring)]"
              style={{ borderColor: problem ? 'var(--warning-ring)' : 'var(--border)' }}
            />
          </label>
          <label>
            <span className="eyebrow block mb-1.5">TO</span>
            <input
              type="date"
              value={shown.end}
              max={today()}
              onChange={e => edit('end', e.target.value)}
              aria-label="Window end date"
              className="h-[30px] px-2 bg-[var(--bg-1)] border rounded-[var(--radius-sm)] font-[var(--font-mono)] text-[12.5px] text-[var(--fg)] outline-none focus:border-[var(--accent-ring)]"
              style={{ borderColor: problem ? 'var(--warning-ring)' : 'var(--border)' }}
            />
          </label>
        </div>
      </div>

      {problem && (
        <p role="alert" className="text-[12px] text-[var(--warning)] leading-relaxed m-0 mt-2">
          {problem} Nothing has been re-simulated.
        </p>
      )}

      {!problem && preset === 'max' && resolvedStart && (
        <p className="text-[12px] text-[var(--fg-2)] leading-relaxed m-0 mt-2">
          As far back as this portfolio goes:{' '}
          <span className="font-[var(--font-mono)]">{resolvedStart}</span> is the earliest
          date any of its holdings has a price here.
        </p>
      )}
    </div>
  );
}
