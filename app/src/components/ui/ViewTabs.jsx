/**
 * ViewTabs — generic segmented tab component.
 *
 * Receives a `tabs` prop shaped as { [tabName]: content }, where each key
 * is the tab's display name and each value is the React node to render
 * while that tab is active. Renders both the tab bar and the active tab's
 * content — the caller supplies all the panels up front, and only the
 * active one is mounted.
 *
 * Uncontrolled by default: it manages its own active-tab state, starting
 * on the first key. Pass `active` (with `onSelect`) to drive the
 * selection from outside instead — App keeps it in the URL, so a view is
 * linkable and survives a reload.
 *
 * Usage:
 *   <ViewTabs tabs={{ Table: <TableView />, Matrix: <MatrixView /> }} />
 *   <ViewTabs tabs={tabs} active="Matrix" onSelect={goToView} />
 */
import { memo, useState } from 'react';

export const ViewTabs = memo(function ViewTabs({ tabs = {}, active: activeProp, onSelect }) {
  const names = Object.keys(tabs);
  const [ownActive, setOwnActive] = useState(names[0]);

  // Controlled as soon as an `active` is supplied; otherwise the internal
  // state drives it, so existing callers keep working unchanged.
  const controlled = activeProp != null;
  const active = controlled ? activeProp : ownActive;

  const setActive = (name) => {
    if (!controlled) setOwnActive(name);
    onSelect?.(name);
  };

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex-none inline-flex self-start p-1 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-md)] gap-0.5 mb-4">
        {names.map(name => {
          const isActive = active === name;
          return (
            <button
              key={name}
              onClick={() => setActive(name)}
              className="flex items-center px-4 py-[7px] border-none rounded-[7px] cursor-pointer font-[var(--font-body)] text-sm transition-all duration-150"
              style={{
                fontWeight: isActive ? 700 : 500,
                background: isActive ? 'var(--bg-3)' : 'transparent',
                color: isActive ? 'var(--fg)' : 'var(--fg-2)',
                boxShadow: isActive ? 'var(--shadow-xs)' : 'none',
              }}
            >
              {name}
            </button>
          );
        })}
      </div>
      <div className="flex-1 min-h-0 flex flex-col">
        {tabs[active]}
      </div>
    </div>
  );
});
