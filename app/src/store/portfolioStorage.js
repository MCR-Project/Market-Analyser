/**
 * portfolioStorage — where simulated portfolios live, which is this
 * browser and nowhere else.
 *
 * A portfolio here is a definition somebody authored, not an account and
 * not a record of anything they own: the app has no sign-in, and its
 * Supabase credentials are the backend's service key, so a server-side
 * table would be one shared, world-editable list. localStorage is the
 * honest place for it — and the simulation itself is stateless (see
 * backend/services/portfolio.py), so nothing else needs to know.
 *
 * Everything here is deliberately defensive. Storage is the one part of a
 * browser app that fails in ways the code did not cause: it is absent in
 * private windows, throws on access when site data is blocked, fills up,
 * and can contain whatever an older build of this app — or the user's own
 * devtools — happened to leave behind. None of that may white-screen the
 * page, so every read is normalised and every failure is reported as a
 * state the UI can explain rather than thrown.
 */

/** The stored shape's version, carried by each portfolio rather than by
 *  the library, so a portfolio stays self-describing when it travels on
 *  its own — a share link (#66) is the same object out of the same
 *  migration. */
export const SCHEMA_VERSION = 1;

export const STORAGE_KEY = 'market-analyser.portfolios';

/** What a new portfolio starts with, in USD — every tracked ticker is
 *  US-listed, and no currency conversion is modelled. */
export const DEFAULT_VALUE = 10000;

/** Mirrors REBALANCE_FREQUENCIES in backend/services/portfolio.py; an
 *  unrecognised value is normalised back to buy and hold. */
export const REBALANCE_FREQUENCIES = ['none', 'monthly', 'quarterly', 'yearly'];

/** Mirrors CONTRIBUTION_FREQUENCIES in backend/services/portfolio.py.
 *  There is no "none" in it: a portfolio with no schedule has no
 *  `contribution` at all, rather than one that is switched off. */
export const CONTRIBUTION_FREQUENCIES = ['monthly', 'quarterly', 'yearly'];

/** What the amount starts at when somebody first turns contributions on,
 *  in USD. A round number that is obviously a placeholder to be changed,
 *  rather than one that looks like a considered choice. */
export const DEFAULT_CONTRIBUTION = 100;

/**
 * How a read went, beyond the portfolios themselves:
 *  - `ok`          storage worked
 *  - `unavailable` storage could not be reached at all (private window,
 *                  blocked site data) — the session still works, it just
 *                  cannot be saved
 *  - `corrupt`     something was there and could not be read as portfolios
 *  - `full`        a write was refused for want of space
 */
export const STORAGE_OK = 'ok';
export const STORAGE_UNAVAILABLE = 'unavailable';
export const STORAGE_CORRUPT = 'corrupt';
export const STORAGE_FULL = 'full';

/** Reading `window.localStorage` is itself what throws when site data is
 *  blocked, so even getting hold of it goes through a try. */
function storage() {
  try {
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

function now() {
  return new Date().toISOString();
}

export function newId() {
  // randomUUID needs a secure context; a plain http:// origin (a LAN dev
  // server, say) has crypto without it, so this falls back rather than
  // throwing on the one call that creates a portfolio.
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `p-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Where a portfolio was seeded from, when it was copied rather than
 *  built by hand. Kept as a note, not a link: the copy is independent
 *  from the moment it exists, and the fund it came from will move on
 *  without it. */
function normaliseSource(raw) {
  if (!raw || typeof raw !== 'object') return undefined;
  if (raw.kind !== 'etf' && raw.kind !== 'portfolio') return undefined;
  if (typeof raw.id !== 'string' || !raw.id) return undefined;
  return {
    kind: raw.kind,
    id: raw.id,
    name: typeof raw.name === 'string' && raw.name ? raw.name : raw.id,
    // The share of the fund's published weights the copy accounted for at
    // the time. Only meaningful for an ETF, and only as history.
    ...(raw.kind === 'etf' && Number.isFinite(raw.coverage) ? { coverage: raw.coverage } : {}),
  };
}

/** An optional recurring contribution: how much, and how often (#67).
 *
 *  Absent is the answer to anything unusable — a missing frequency, a
 *  frequency this build does not have, an amount that is not a positive
 *  number. A portfolio whose schedule cannot be read is a portfolio with
 *  no schedule, which simulates as the lump sum it always did; the
 *  alternative is guessing at a frequency and putting money in on dates
 *  nobody chose. */
function normaliseContribution(raw) {
  if (!raw || typeof raw !== 'object') return undefined;
  if (!CONTRIBUTION_FREQUENCIES.includes(raw.frequency)) return undefined;
  if (!Number.isFinite(raw.amount) || raw.amount <= 0) return undefined;
  return { amount: raw.amount, frequency: raw.frequency };
}

function normaliseHoldings(raw) {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter(h => h && typeof h.ticker === 'string' && h.ticker.trim())
    .map(h => ({
      ticker: h.ticker.trim().toUpperCase(),
      weight: Number.isFinite(h.weight) && h.weight >= 0 ? h.weight : 0,
    }));
}

/**
 * Bring one stored entry up to the current shape, or return null if it is
 * not a portfolio at all.
 *
 * This is the migration path: version 1 needs no rewriting, so the work
 * it does today is coercing each field to something usable and dropping
 * entries that are past saving. A version 2 adds its step here, keyed off
 * `schemaVersion`, and every reader — the library below, and a share link
 * later — gets it at once by going through this one function.
 *
 * Unknown fields are preserved rather than stripped: a portfolio written
 * by a newer build and then opened by an older one should come back
 * intact rather than quietly losing whatever that build added.
 */
export function migratePortfolio(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const name = typeof raw.name === 'string' && raw.name.trim() ? raw.name.trim() : null;
  if (!name) return null;

  return {
    ...raw,
    id: typeof raw.id === 'string' && raw.id ? raw.id : newId(),
    schemaVersion: SCHEMA_VERSION,
    name,
    value: Number.isFinite(raw.value) && raw.value > 0 ? raw.value : DEFAULT_VALUE,
    holdings: normaliseHoldings(raw.holdings),
    rebalance: REBALANCE_FREQUENCIES.includes(raw.rebalance) ? raw.rebalance : 'none',
    // Added after version 1 was already in people's browsers, and
    // optional, so an older record simply has none - which is exactly
    // what "off by default" has to look like on read.
    contribution: normaliseContribution(raw.contribution),
    createdAt: typeof raw.createdAt === 'string' ? raw.createdAt : now(),
    updatedAt: typeof raw.updatedAt === 'string' ? raw.updatedAt : now(),
    source: normaliseSource(raw.source),
  };
}

/**
 * Read the library.
 *
 * Always returns an array and a status, never throws: a first visit and a
 * blocked storage and a half-written value all have to leave the page
 * standing, differing only in what it can honestly say afterwards.
 */
export function loadPortfolios() {
  const store = storage();
  if (!store) return { portfolios: [], status: STORAGE_UNAVAILABLE };

  let raw;
  try {
    raw = store.getItem(STORAGE_KEY);
  } catch {
    return { portfolios: [], status: STORAGE_UNAVAILABLE };
  }
  // Nothing stored is a first visit, not a fault.
  if (raw == null) return { portfolios: [], status: STORAGE_OK };

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { portfolios: [], status: STORAGE_CORRUPT };
  }
  if (!Array.isArray(parsed)) return { portfolios: [], status: STORAGE_CORRUPT };

  const portfolios = parsed.map(migratePortfolio).filter(Boolean);
  // Something was stored, and none of it survived reading: say so rather
  // than presenting an empty library as though it had always been empty.
  if (parsed.length > 0 && portfolios.length === 0) {
    return { portfolios: [], status: STORAGE_CORRUPT };
  }
  return { portfolios, status: STORAGE_OK };
}

/**
 * Write the library, reporting how it went rather than throwing. A
 * refused write is not a reason to lose what the session already has in
 * memory — the caller keeps its state and tells the user it is not being
 * saved.
 */
export function savePortfolios(portfolios) {
  const store = storage();
  if (!store) return STORAGE_UNAVAILABLE;
  try {
    store.setItem(STORAGE_KEY, JSON.stringify(portfolios));
    return STORAGE_OK;
  } catch (err) {
    // Browsers disagree on the name and the code, and Safari reports a
    // full quota in private mode as a plain security error, so both are
    // treated as "no room" — the user-facing difference is nil.
    const quota =
      err?.name === 'QuotaExceededError' ||
      err?.name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
      err?.code === 22;
    return quota ? STORAGE_FULL : STORAGE_UNAVAILABLE;
  }
}

/** A name no existing portfolio has, so a run of Create presses does not
 *  produce a list of identical rows. */
export function untitledName(existing) {
  const taken = new Set(existing.map(p => p.name));
  if (!taken.has('New portfolio')) return 'New portfolio';
  for (let n = 2; ; n += 1) {
    const candidate = `New portfolio ${n}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** A blank portfolio, or one seeded from `seed` — a fund's constituents,
 *  or another portfolio's, with `source` recording which. */
export function makePortfolio(seed = {}) {
  const timestamp = now();
  return {
    id: newId(),
    schemaVersion: SCHEMA_VERSION,
    name: seed.name || 'New portfolio',
    value: Number.isFinite(seed.value) && seed.value > 0 ? seed.value : DEFAULT_VALUE,
    holdings: normaliseHoldings(seed.holdings),
    rebalance: REBALANCE_FREQUENCIES.includes(seed.rebalance) ? seed.rebalance : 'none',
    contribution: normaliseContribution(seed.contribution),
    createdAt: timestamp,
    updatedAt: timestamp,
    source: normaliseSource(seed.source),
  };
}

/** "Name (copy)", "Name (copy 2)", … so duplicating twice is legible. */
export function copyName(name, existing) {
  const taken = new Set(existing.map(p => p.name));
  const base = `${name} (copy)`;
  if (!taken.has(base)) return base;
  for (let n = 2; ; n += 1) {
    const candidate = `${name} (copy ${n})`;
    if (!taken.has(candidate)) return candidate;
  }
}
