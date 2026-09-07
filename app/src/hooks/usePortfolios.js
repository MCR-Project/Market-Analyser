/**
 * usePortfolios — the saved portfolio library, as React state.
 *
 * Reads once on mount and writes through on every change, so what is on
 * screen and what is in storage never drift. A refused write (storage
 * blocked, quota full) does not roll the change back: the session keeps
 * working with what it has and the page says plainly that it is not being
 * saved, which is more useful than a change that silently undoes itself.
 *
 * The library is small and one page uses it, so it is plain state rather
 * than a context or a store — the same reasoning that keeps the ETF
 * selection in the URL rather than in a global.
 */
import { useCallback, useRef, useState } from 'react';
import {
  STORAGE_CORRUPT,
  STORAGE_OK,
  copyName,
  loadPortfolios,
  makePortfolio,
  savePortfolios,
  untitledName,
} from '../store/portfolioStorage';

/** Newest first: the one just created or just touched is the one being
 *  looked for. */
function ordered(portfolios) {
  return [...portfolios].sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''));
}

/** A successful write clears a previous complaint, but never clears
 *  `corrupt`: that describes what was already in storage when the page
 *  loaded, and saving over it does not un-lose it. */
function nextStatus(current, written) {
  if (written !== STORAGE_OK) return written;
  return current === STORAGE_CORRUPT ? STORAGE_CORRUPT : STORAGE_OK;
}

export function usePortfolios() {
  // Read in the initialiser rather than in an effect, so the first paint
  // already knows whether there are portfolios and the empty state never
  // flashes in front of somebody who has ten of them.
  const [state, setState] = useState(() => {
    const { portfolios, status } = loadPortfolios();
    return { portfolios: ordered(portfolios), status };
  });

  // The list as it stands, readable synchronously. Every mutation derives
  // the next library from this rather than from inside a setState
  // updater: naming a new portfolio has to read the existing names, and
  // an updater that ran twice (as React does in development) would mint
  // two ids and hand back the wrong one.
  const listRef = useRef(state.portfolios);

  const mutate = useCallback((change) => {
    const next = change(listRef.current);
    if (next === listRef.current) return;
    const written = savePortfolios(next);
    listRef.current = ordered(next);
    setState(current => ({ portfolios: listRef.current, status: nextStatus(current.status, written) }));
  }, []);

  const create = useCallback((seed = {}) => {
    const created = makePortfolio({
      ...seed,
      name: seed.name || untitledName(listRef.current),
    });
    mutate(list => [...list, created]);
    return created;
  }, [mutate]);

  const update = useCallback((id, changes) => {
    mutate(list => list.map(p => (
      p.id === id ? { ...p, ...changes, updatedAt: new Date().toISOString() } : p
    )));
  }, [mutate]);

  const rename = useCallback((id, name) => {
    const trimmed = name.trim();
    // An empty name would leave a row with nothing to click and nothing
    // to say, so the old one stands.
    if (trimmed) update(id, { name: trimmed });
  }, [update]);

  const duplicate = useCallback((id) => {
    const source = listRef.current.find(p => p.id === id);
    if (!source) return null;
    const copy = makePortfolio({ ...source, name: copyName(source.name, listRef.current) });
    mutate(list => [...list, copy]);
    return copy;
  }, [mutate]);

  const remove = useCallback((id) => {
    mutate(list => list.filter(p => p.id !== id));
  }, [mutate]);

  return {
    portfolios: state.portfolios,
    status: state.status,
    create,
    update,
    rename,
    duplicate,
    remove,
  };
}
