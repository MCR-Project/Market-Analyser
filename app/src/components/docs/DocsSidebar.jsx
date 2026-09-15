/**
 * DocsSidebar — the list of measurements and portfolio metrics you can
 * read about, and a search box for finding one.
 *
 * Built entirely from the backend manifest(s), grouped by each entry's
 * `origin`. That grouping is the point: a measurement plugged into
 * addon_measurements/ shows up under "Plugged-in measurements" on its own,
 * with nothing to add here — the same property that lets an addon ship its
 * own documentation — and a portfolio metric (issue #104) joins as a third
 * group the same way, from its own registry, with nothing here needing to
 * know the two registries are different beyond the `origin` they stamp.
 *
 * A multi-column measurement (issue #100, first shipped for real by issue
 * #107) contributes one manifest row per column, all sharing one `.mdx`
 * doc — deduplicated here to a single link per plugin (`measurement_id`,
 * which is already just `id` for every other kind of entry), pointing at
 * the plugin's own id rather than any one column's namespaced one, the
 * same id `DocLink` in the table links to. Without this, "Beta / R² /
 * Idiosyncratic Volatility" would list itself three times.
 *
 * Search filters name and description only. Both are already in the
 * manifest the page fetched anyway, so filtering is instant and needs no
 * request; the doc bodies are deliberately not searched.
 */
import { memo, useMemo } from 'react';
import { NavLink } from 'react-router';

const GROUPS = [
  { origin: 'official', label: 'Official measurements' },
  { origin: 'addon', label: 'Plugged-in measurements' },
  { origin: 'portfolio', label: 'Portfolio metrics' },
];

function matches(measurement, query) {
  if (!query) return true;
  const haystack = `${measurement.name} ${measurement.description}`.toLowerCase();
  return haystack.includes(query.toLowerCase().trim());
}

/** One row per plugin rather than per column — first row wins for a
 *  shared id, and manifest order is preserved. */
function dedupeByPlugin(manifest) {
  const seen = new Set();
  const out = [];
  for (const m of manifest) {
    const linkId = m.measurement_id ?? m.id;
    if (seen.has(linkId)) continue;
    seen.add(linkId);
    out.push({ ...m, linkId });
  }
  return out;
}

export const DocsSidebar = memo(function DocsSidebar({ manifest, query, onQueryChange }) {
  const deduped = useMemo(() => dedupeByPlugin(manifest), [manifest]);
  const visible = deduped.filter(m => matches(m, query));

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
            {visible.length}/{deduped.length}
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
                  <li key={m.linkId}>
                    <NavLink
                      to={`/docs/${m.linkId}`}
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
