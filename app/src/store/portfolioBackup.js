/**
 * portfolioBackup — a whole library, or one portfolio, as a file (issue #148).
 *
 * Portfolios live in one browser's storage and nowhere else
 * (portfolioStorage.js), and deleting one cannot be undone, so clearing
 * site data, changing browser or changing machine loses every one of
 * them. A **Backup** is the way out: a JSON file the owner keeps wherever
 * they like, **Exported** from one browser and **Imported** into any
 * other. It is not a Share Link (portfolioLink.js). A link is a
 * *definition* for somebody else to look at: no identity, no dates, read-only
 * until they keep it. A Backup is the owner's own library at full
 * fidelity, and what comes out of an Import is ordinary saved portfolios.
 *
 * ## The file
 *
 * One envelope for everything - `{ format, exportedAt, portfolios }` - so
 * a single portfolio is a list of one and Import has exactly one path. A
 * bare list is accepted too, because it is precisely what localStorage
 * holds and somebody may have copied it out of devtools. The envelope has
 * no version of its own: each portfolio carries its `schemaVersion` and
 * `migratePortfolio` upgrades it on read, so a second number could only
 * disagree with the first (ADR 0001). The `format` marker is the one place
 * a future envelope would be told apart from this one.
 *
 * What travels is the portfolio as the session holds it - id, dates,
 * origin note, contribution schedule, and any fields a newer build added
 * that this one does not know. What does not is view state: the window,
 * the benchmark and the comparison live in the URL because they belong to
 * the way somebody is looking, not to the portfolio.
 *
 * ## Import only ever adds
 *
 * It never replaces or deletes anything already saved (ADR 0001): the
 * library is this browser's storage with no undo, and an import that
 * overwrote could let a stale file erase newer work in silence. A portfolio
 * is identified by its `id`:
 *
 *  - the same `id` and every field equal is *identical* - skipped, and
 *    reported, so importing one file twice does not fill the library
 *  - the same `id` with different content is somebody's earlier or later
 *    version - added under a fresh `id`, so the list never has two rows
 *    behind one URL and both versions survive
 *  - a different `id` is a different portfolio, however alike: a deliberate
 *    Duplicate must not be mistaken for a repeat
 *
 * A name that is taken gets `-2`, `-3`, … on the end, appended as it
 * stands. Collisions are checked against the library *and everything
 * already added from the same file*, in file order, so a file cannot
 * collide with itself.
 *
 * ## Trust
 *
 * A Backup is chosen by the person importing it, which puts it between the
 * two other readers of a portfolio: `migratePortfolio` salvages what it can
 * because the alternative is losing somebody's work, and `decodePortfolio`
 * refuses the whole payload because a link is somebody else's input. Import
 * salvages per entry - each goes through `migratePortfolio` unchanged - and
 * then holds the result to the limits that migration deliberately does not
 * enforce, because a portfolio that imports happily and then cannot be
 * simulated is a portfolio that is broken twice: no more than
 * MAX_LINK_HOLDINGS holdings, no ticker twice, every ticker a ticker. An
 * entry failing one is skipped and named with its reason, never quietly
 * trimmed. Only a file that is not a Backup at all, is too large, or has
 * nothing in it that can be imported is refused whole - and then nothing is
 * written, which the message says.
 *
 * Nothing here reads or writes storage or touches the page: `planImport` is a
 * pure function of the library and the file's text, `exportLibrary` and
 * `exportOne` only build the file, and `usePortfolios` applies what
 * `planImport` returns. Saving a file is `utils/downloadFile.js`'s job.
 */
import { MAX_LINK_HOLDINGS, TICKER_PATTERN } from './portfolioLink';
import { migratePortfolio, newId } from './portfolioStorage';

/** What the envelope's `format` says. A fixed string naming this app's
 *  portfolios; the shortened `ma-` is for filenames only. */
export const BACKUP_FORMAT = 'market-analyser-portfolios';

/** The ceiling on a file, checked before it is read - the point of a size
 *  limit is to refuse work, not to do it first. A full 50-holding portfolio
 *  is a few kilobytes, so this leaves room for hundreds of them without
 *  leaving the door open. */
export const MAX_BACKUP_BYTES = 2 * 1024 * 1024;

const UNCHANGED = 'Nothing has been changed.';
const NOT_JSON = `This file could not be read as JSON, so it is not a portfolio backup. ${UNCHANGED}`;
const NOT_A_BACKUP = `This file is not a portfolio backup. ${UNCHANGED}`;
const NO_LIST = `This backup has no list of portfolios in it. ${UNCHANGED}`;
const EMPTY = `This backup contains no portfolios. ${UNCHANGED}`;
const TOO_LARGE = `This file is too large to be a portfolio backup. ${UNCHANGED}`;
const UNREADABLE = `This file could not be read. ${UNCHANGED}`;
const NONE_USABLE = `None of the portfolios in this file could be imported. ${UNCHANGED}`;
const NOT_A_PORTFOLIO = 'It is not a portfolio, or it has no name.';

/** Refusals and successes have the same shape, so callers never have to ask
 *  which one they got. `failed` is kept on a refusal: a file in which every
 *  entry was bad is best explained by saying what was wrong with each. */
export function refused(message, failed = []) {
  return { error: message, added: [], renamed: [], skipped: [], failed };
}

/** Two portfolios as data, ignoring key order and keys that are undefined:
 *  a migrated portfolio has `contribution: undefined` where the same one
 *  read back from JSON simply has no such key. */
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .filter(key => value[key] !== undefined)
        .map(key => [key, canonical(value[key])])
    );
  }
  return value;
}

function identical(a, b) {
  return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
}

/** The first thing wrong with an entry `migratePortfolio` was content to
 *  keep, or null. These are the rules `decodePortfolio` applies to a link
 *  and migration does not apply to storage. */
function problemWith(portfolio) {
  if (portfolio.holdings.length > MAX_LINK_HOLDINGS) {
    return `It holds more than ${MAX_LINK_HOLDINGS} holdings, which is more than a portfolio here can hold.`;
  }
  const seen = new Set();
  for (const { ticker } of portfolio.holdings) {
    if (!TICKER_PATTERN.test(ticker)) {
      // Shown as text and never built into anything: this is somebody's
      // file, so what it says is not trusted with more than that.
      return `“${ticker.slice(0, 20)}” is not a ticker symbol.`;
    }
    if (seen.has(ticker)) return `It holds ${ticker} twice.`;
    seen.add(ticker);
  }
  return null;
}

/** `name` if nothing has it, otherwise the first of `name-2`, `name-3`, … that
 *  nothing has. Appended as it stands: a name that already ends in a number
 *  is the person's own, and is not reinterpreted. */
function freeName(name, taken) {
  if (!taken.has(name)) return name;
  for (let n = 2; ; n += 1) {
    const candidate = `${name}-${n}`;
    if (!taken.has(candidate)) return candidate;
  }
}

function freeId(taken) {
  let id = newId();
  while (taken.has(id)) id = newId();
  return id;
}

/** The entries of a parsed file, or the message for why it has none. */
function entriesOf(parsed) {
  if (Array.isArray(parsed)) return { entries: parsed };
  if (!parsed || typeof parsed !== 'object' || parsed.format !== BACKUP_FORMAT) {
    return { error: NOT_A_BACKUP };
  }
  return Array.isArray(parsed.portfolios) ? { entries: parsed.portfolios } : { error: NO_LIST };
}

/**
 * What importing `text` into `existing` would do.
 *
 * Returns `{ error, added, renamed, skipped, failed }`, and never throws:
 *  - `error`   a message when the whole file is refused, otherwise null
 *  - `added`   the portfolios to add, exactly as they should be stored -
 *              final names and ids, the file's own dates
 *  - `renamed` `{ from, to }` for each one whose name was taken
 *  - `skipped` names of those identical to one already saved
 *  - `failed`  `{ name, reason }` for each entry that could not be imported
 *
 * Does nothing to `existing`; the caller writes `added` if it wants them.
 */
export function planImport(existing, text) {
  if (typeof text !== 'string' || text.length > MAX_BACKUP_BYTES) return refused(TOO_LARGE);

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return refused(NOT_JSON);
  }

  const { entries, error } = entriesOf(parsed);
  if (error) return refused(error);
  if (entries.length === 0) return refused(EMPTY);

  // What the library will hold as the import proceeds: the portfolios
  // already saved plus each one added so far, so a file is checked against
  // itself as well as against what was there.
  const pool = [...existing];
  const ids = new Set(pool.map(p => p.id));
  const names = new Set(pool.map(p => p.name));
  // Each entry added so far *as the file wrote it*, before it was renamed or
  // given a fresh id. A repeat within the file is compared with these and
  // not with the copy in `pool`: that one may have been renamed to fit, and
  // an entry is not a different portfolio just because its first appearance
  // had to be.
  const fromFile = [];

  const added = [];
  const renamed = [];
  const skipped = [];
  const failed = [];

  entries.forEach((raw, index) => {
    const migrated = migratePortfolio(raw);
    if (!migrated) {
      failed.push({ name: `Entry ${index + 1}`, reason: NOT_A_PORTFOLIO });
      return;
    }
    const problem = problemWith(migrated);
    if (problem) {
      failed.push({ name: migrated.name, reason: problem });
      return;
    }

    const twin = pool.find(p => p.id === migrated.id);
    if ((twin && identical(twin, migrated)) || fromFile.some(entry => identical(entry, migrated))) {
      skipped.push(migrated.name);
      return;
    }

    const name = freeName(migrated.name, names);
    const portfolio = {
      ...migrated,
      // The same id with other content is a different version of somebody's
      // portfolio, and the list must never have two rows behind one URL.
      id: twin ? freeId(ids) : migrated.id,
      name,
    };
    if (name !== migrated.name) renamed.push({ from: migrated.name, to: name });

    pool.push(portfolio);
    fromFile.push(migrated);
    ids.add(portfolio.id);
    names.add(name);
    added.push(portfolio);
  });

  if (added.length === 0 && skipped.length === 0) return refused(NONE_USABLE, failed);
  return { error: null, added, renamed, skipped, failed };
}

/**
 * Read a picked file into text, or say why not. The size is the file's own
 * report, checked before a byte of it is read; `planImport` checks the text
 * again for callers that did not come through here.
 */
export async function readBackupFile(file) {
  if (file.size > MAX_BACKUP_BYTES) return { error: TOO_LARGE };
  try {
    return { text: await file.text() };
  } catch {
    return { error: UNREADABLE };
  }
}

// ── Export ───────────────────────────────────────────────────────────────

/** The export date as the person's own calendar has it - a backup made in
 *  the evening should not be named for tomorrow. */
function dayStamp(date) {
  const pad = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** A name as the middle of a filename: lower case, letters and digits
 *  joined by single hyphens, accents folded. Names can hold anything, and
 *  Windows refuses several characters a name may legitimately contain, so
 *  everything else goes. A name with nothing usable in it (or in a script
 *  this cannot fold) falls back to a plain word rather than an empty slot. */
function slug(name) {
  const cut = String(name || '')
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
    .replace(/-+$/, '');
  return cut || 'portfolio';
}

function exportFile(portfolios, label, now) {
  const envelope = { format: BACKUP_FORMAT, exportedAt: now.toISOString(), portfolios };
  return {
    filename: `ma-${label}-${dayStamp(now)}.json`,
    // Indented: the file is somebody's to open, read and diff, and it is a
    // few kilobytes either way.
    text: JSON.stringify(envelope, null, 2),
  };
}

/** The whole library, as `{ filename, text }`. */
export function exportLibrary(portfolios, now = new Date()) {
  return exportFile(portfolios, 'portfolios', now);
}

/** One portfolio - a Backup of one, so Import needs no second path. */
export function exportOne(portfolio, now = new Date()) {
  return exportFile([portfolio], slug(portfolio.name), now);
}
