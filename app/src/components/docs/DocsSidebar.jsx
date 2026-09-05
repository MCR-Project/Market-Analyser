/**
 * DocsSidebar — the list of measurements you can read about, and a search
 * box for finding one.
 *
 * Built entirely from the backend manifest, grouped by each measurement's
 * `origin`. That grouping is the point: a measurement plugged into
 * addon_measurements/ shows up under "Plugged-in measurements" on its own,
 * with nothing to add here — the same property that lets an addon ship its
 * own documentation.
 *
 * Search filters name and description only. Both are already in the
 * manifest the page fetched anyway, so filtering is instant and needs no
 * request; the doc bodies are deliberately not searched.
 */
import { memo } from 'react';
import { NavLink } from 'react-router';

const GROUPS = [
  { origin: 'official', label: 'Official measurements' },
  { origin: 'addon', label: 'Plugged-in measurements' },
];

function matches(measurement, query) {
  if (!query) return true;
  const haystack = `${measurement.name} ${measurement.description}`.toLowerCase();
  return haystack.includes(query.toLowerCase().trim());
}

export const DocsSidebar = memo(function DocsSidebar({ manifest, query, onQueryChange }) {
  const visible = manifest.filter(m => matches(m, query));

  return (
    <nav aria-label="Measurements" className="flex flex-col gap-4 min-h-0">
      <div className="flex items-center gap-2 h-[38px] px-3 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-md)] focus-within:border-[var(--accent-ring)]">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--fg-2)] flex-none" aria-hidden="true">
          <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
        </svg>
        <input
          type="search"
          value={query}
          onInput={e => onQueryChange(e.target.value)}
          placeholder="Search measurements…"
          aria-label="Search measurements by name or description"
          className="flex-1 min-w-0 border-none outline-none bg-transparent text-[var(--fg)] font-[var(--font-body)] text-[13px]"
        />
        {query && (
          <span className="font-[var(--font-mono)] text-[10px] text-[var(--fg-3)] flex-none">
            {visible.length}/{manifest.length}
          </span>
        )}
      </div>

      {visible.length === 0 ? (
        <p className="text-[13px] text-[var(--fg-2)] m-0 px-1">
          No measurement matches “{query}”.
        </p>
      ) : (
        GROUPS.map(group => {
          const items = visible.filter(m => (m.origin || 'official') === group.origin);
          if (items.length === 0) return null;

          return (
            <div key={group.origin}>
              <div className="eyebrow mb-2 px-1">{group.label}</div>
              <ul className="list-none m-0 p-0 flex flex-col gap-0.5">
                {items.map(m => (
                  <li key={m.id}>
                    <NavLink
                      to={`/docs/${m.id}`}
                      className="block px-3 py-2 rounded-[var(--radius-sm)] no-underline transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] aria-[current=page]:bg-[var(--accent-soft)] hover:bg-[var(--bg-2)]"
                    >
                      {({ isActive }) => (
                        <>
                          <div
                            className="text-[13.5px] leading-snug"
                            style={{
                              color: isActive ? 'var(--accent)' : 'var(--fg)',
                              fontWeight: isActive ? 700 : 500,
                            }}
                          >
                            {m.name}
                          </div>
                          <div className="text-[11.5px] leading-snug text-[var(--fg-2)] mt-0.5 line-clamp-2">
                            {m.description}
                          </div>
                        </>
                      )}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          );
        })
      )}
    </nav>
  );
});
