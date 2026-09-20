/**
 * portfolioBackup — the seam the export/import feature's rules are tested
 * at (issue #148): `planImport`, given the library as it stands and the
 * text of a file, says what importing it would do. Export is covered
 * through what it writes: the file is round-tripped back through that same
 * function, and its filenames are asserted directly.
 *
 * Plain functions and inline data, no DOM: nothing here touches storage,
 * the network or the page, because nothing under test does. Generated ids
 * are never asserted on by value - only that a fresh one is not one the
 * library already has.
 */
import { expect, test } from 'vitest';
import {
  BACKUP_FORMAT,
  MAX_BACKUP_BYTES,
  exportLibrary,
  exportOne,
  planImport,
} from './portfolioBackup';
import { migratePortfolio } from './portfolioStorage';

const T0 = '2026-01-05T10:00:00.000Z';
const T1 = '2026-02-06T11:30:00.000Z';

/** A saved portfolio as the library holds it - already through the
 *  migration, with fixed dates so two of them can be identical. */
function saved(overrides = {}) {
  return migratePortfolio({
    id: 'a',
    name: 'Semis',
    value: 5000,
    holdings: [{ ticker: 'NVDA', weight: 60 }, { ticker: 'AMD', weight: 40 }],
    rebalance: 'quarterly',
    createdAt: T0,
    updatedAt: T1,
    ...overrides,
  });
}

/** The text of a Backup holding `portfolios`, written the way Export does. */
function backup(portfolios) {
  return exportLibrary(portfolios).text;
}

/** A hand-made file, for what Export would never write. */
function envelope(portfolios, extra = {}) {
  return JSON.stringify({ format: BACKUP_FORMAT, exportedAt: T1, portfolios, ...extra });
}

const NOTHING = { added: [], renamed: [], skipped: [], failed: [] };

// ── Refusing the whole file ─────────────────────────────────────────────

test('a file that is not JSON is refused, and nothing is planned', () => {
  const plan = planImport([saved()], '{"format": "market-anal');
  expect(plan.error).toMatch(/not a portfolio backup|could not be read/i);
  expect(plan).toMatchObject(NOTHING);
});

test.each([
  ['a number', '42'],
  ['a string', '"portfolios"'],
  ['null', 'null'],
  ['an object with no format marker', JSON.stringify({ portfolios: [{ name: 'X' }] })],
  ['an object with another format marker', JSON.stringify({ format: 'something-else', portfolios: [{ name: 'X' }] })],
])('%s is not a Backup', (_label, text) => {
  const plan = planImport([], text);
  expect(plan.error).toMatch(/not a portfolio backup/i);
  expect(plan).toMatchObject(NOTHING);
});

test('an envelope whose portfolios are not a list is refused', () => {
  const plan = planImport([], JSON.stringify({ format: BACKUP_FORMAT, portfolios: { name: 'X' } }));
  expect(plan.error).toBeTruthy();
  expect(plan).toMatchObject(NOTHING);
});

test('an empty Backup is refused rather than reported as a success', () => {
  const plan = planImport([saved()], envelope([]));
  expect(plan.error).toMatch(/no portfolios/i);
  expect(plan).toMatchObject(NOTHING);
});

test('a file over the size ceiling is refused', () => {
  const plan = planImport([], ' '.repeat(MAX_BACKUP_BYTES + 1));
  expect(plan.error).toMatch(/too large/i);
  expect(plan).toMatchObject(NOTHING);
});

test('a file in which nothing can be saved is refused, with the reasons kept', () => {
  const plan = planImport([], envelope([{ value: 100 }, 'nope', { name: '   ' }]));
  expect(plan.error).toBeTruthy();
  expect(plan.added).toEqual([]);
  expect(plan.failed).toHaveLength(3);
});

// ── What a file may look like ───────────────────────────────────────────

test('a bare list of portfolios, as localStorage holds it, is accepted', () => {
  const plan = planImport([], JSON.stringify([saved(), saved({ id: 'b', name: 'Energy' })]));
  expect(plan.error).toBeNull();
  expect(plan.added.map(p => p.name)).toEqual(['Semis', 'Energy']);
});

test('a hand-made entry with only a name is salvaged with the usual defaults', () => {
  const plan = planImport([], envelope([{ name: '  Bare  ' }]));
  expect(plan.error).toBeNull();
  expect(plan.added).toHaveLength(1);
  expect(plan.added[0]).toMatchObject({
    name: 'Bare',
    value: 10000,
    holdings: [],
    rebalance: 'none',
    schemaVersion: 1,
  });
  expect(typeof plan.added[0].id).toBe('string');
  expect(plan.added[0].id).not.toBe('');
});

test('fields this build does not know about survive the trip', () => {
  const plan = planImport([], envelope([{ ...saved(), tag: 'from-a-newer-build', notes: { pinned: true } }]));
  expect(plan.added[0]).toMatchObject({ tag: 'from-a-newer-build', notes: { pinned: true } });
});

test("the file's own dates are kept, not replaced by the moment of import", () => {
  const plan = planImport([], backup([saved()]));
  expect(plan.added[0].createdAt).toBe(T0);
  expect(plan.added[0].updatedAt).toBe(T1);
});

test('a recurring contribution and an origin note come across unchanged', () => {
  const original = saved({
    contribution: { amount: 250, frequency: 'monthly' },
    source: { kind: 'etf', id: 'SMH', name: 'VanEck Semiconductor', coverage: 71.2 },
  });
  const plan = planImport([], backup([original]));
  expect(plan.added[0].contribution).toEqual({ amount: 250, frequency: 'monthly' });
  expect(plan.added[0].source).toEqual(original.source);
});

test('a recurring withdrawal comes across unchanged (#150)', () => {
  const original = saved({ withdrawal: { amount: 500, frequency: 'quarterly' } });
  const plan = planImport([], backup([original]));
  expect(plan.added[0].withdrawal).toEqual({ amount: 500, frequency: 'quarterly' });
  expect(plan.added[0].contribution).toBeUndefined();
});

// ── Identical, different, and the same identity ─────────────────────────

test('importing what the library already holds skips it, and says which', () => {
  const library = [saved(), saved({ id: 'b', name: 'Energy' })];
  const plan = planImport(library, backup(library));
  expect(plan.error).toBeNull();
  expect(plan.added).toEqual([]);
  expect(plan.renamed).toEqual([]);
  expect(plan.failed).toEqual([]);
  expect(plan.skipped).toEqual(['Semis', 'Energy']);
});

test('the same id with different content is added, under an id the library does not have', () => {
  const library = [saved()];
  const edited = saved({ holdings: [{ ticker: 'NVDA', weight: 100 }], updatedAt: '2026-03-01T00:00:00.000Z' });
  const plan = planImport(library, backup([edited]));
  expect(plan.skipped).toEqual([]);
  expect(plan.added).toHaveLength(1);
  expect(plan.added[0].id).not.toBe('a');
  expect(plan.added[0].holdings).toEqual(edited.holdings);
});

test('a different id with the same content is a different portfolio, not a repeat', () => {
  // What Duplicate leaves behind, before anybody renames it.
  const library = [saved()];
  const plan = planImport(library, backup([saved({ id: 'b' })]));
  expect(plan.skipped).toEqual([]);
  expect(plan.added).toHaveLength(1);
  expect(plan.added[0].id).toBe('b');
  expect(plan.added[0].name).toBe('Semis-2');
});

test('a difference in any field stops a portfolio counting as identical', () => {
  const changes = [
    { name: 'Semiconductors' },
    { value: 5001 },
    { rebalance: 'yearly' },
    { holdings: [{ ticker: 'NVDA', weight: 60 }, { ticker: 'AMD', weight: 41 }] },
    { contribution: { amount: 100, frequency: 'monthly' } },
    { withdrawal: { amount: 100, frequency: 'monthly' } },
    { updatedAt: '2026-02-06T11:30:01.000Z' },
  ];
  for (const change of changes) {
    const plan = planImport([saved()], backup([saved(change)]));
    expect(plan.skipped, JSON.stringify(change)).toEqual([]);
    expect(plan.added, JSON.stringify(change)).toHaveLength(1);
  }
});

test('a file with no timestamps never matches, because migration mints "now" for them', () => {
  const library = [saved()];
  const undated = { ...library[0] };
  delete undated.createdAt;
  delete undated.updatedAt;
  const plan = planImport(library, envelope([undated]));
  expect(plan.skipped).toEqual([]);
  expect(plan.added).toHaveLength(1);
  expect(plan.added[0].id).not.toBe('a');
});

// ── Names ───────────────────────────────────────────────────────────────

test('a name that is taken gets -2', () => {
  const plan = planImport([saved()], backup([saved({ id: 'z', holdings: [] })]));
  expect(plan.added.map(p => p.name)).toEqual(['Semis-2']);
  expect(plan.renamed).toEqual([{ from: 'Semis', to: 'Semis-2' }]);
});

test('the next free number is used when -2 is taken too', () => {
  const library = [saved(), saved({ id: 'b', name: 'Semis-2' })];
  const plan = planImport(library, backup([saved({ id: 'z', holdings: [] })]));
  expect(plan.added.map(p => p.name)).toEqual(['Semis-3']);
  expect(plan.renamed).toEqual([{ from: 'Semis', to: 'Semis-3' }]);
});

test('a name that is free is left alone', () => {
  const plan = planImport([saved()], backup([saved({ id: 'z', name: 'Energy' })]));
  expect(plan.added.map(p => p.name)).toEqual(['Energy']);
  expect(plan.renamed).toEqual([]);
});

test('the suffix is appended as it stands, so a name that already ends in a number keeps it', () => {
  const library = [saved({ name: 'Q3-2025' })];
  const plan = planImport(library, backup([saved({ id: 'z', name: 'Q3-2025', holdings: [] })]));
  expect(plan.added.map(p => p.name)).toEqual(['Q3-2025-2']);
});

test('two portfolios in one file that share a name cannot collide with each other', () => {
  const file = envelope([
    saved({ id: 'x', name: 'Semis' }),
    saved({ id: 'y', name: 'Semis', holdings: [] }),
    saved({ id: 'w', name: 'Semis', holdings: [{ ticker: 'TSM', weight: 100 }] }),
  ]);
  const plan = planImport([], file);
  expect(plan.added.map(p => p.name)).toEqual(['Semis', 'Semis-2', 'Semis-3']);
  expect(plan.renamed).toEqual([
    { from: 'Semis', to: 'Semis-2' },
    { from: 'Semis', to: 'Semis-3' },
  ]);
});

test('two portfolios in one file with the same id cannot collide with each other', () => {
  const file = envelope([
    saved({ id: 'x', name: 'One' }),
    saved({ id: 'x', name: 'Two' }),
  ]);
  const plan = planImport([], file);
  expect(plan.added).toHaveLength(2);
  expect(new Set(plan.added.map(p => p.id)).size).toBe(2);
});

test('a repeat of an entry already added from the same file is skipped, not added twice', () => {
  const plan = planImport([], envelope([saved(), saved()]));
  expect(plan.added).toHaveLength(1);
  expect(plan.skipped).toEqual(['Semis']);
});

test('a repeat is still recognised when the first copy had to be renamed or given a new id', () => {
  // The first entry is added as "Semis-2" (its name is taken); the second is
  // the same entry again, and has to be compared with what the file said,
  // not with the renamed copy that was made of it.
  const library = [saved({ id: 'z', holdings: [] })];
  const plan = planImport(library, envelope([saved(), saved()]));
  expect(plan.added.map(p => p.name)).toEqual(['Semis-2']);
  expect(plan.skipped).toEqual(['Semis']);

  // And the same when it was the id that collided: the library's "a" is a
  // different version, so the first copy takes a fresh id.
  const other = [saved({ value: 1 })];
  const again = planImport(other, envelope([saved(), saved()]));
  expect(again.added).toHaveLength(1);
  expect(again.added[0].id).not.toBe('a');
  expect(again.skipped).toEqual(['Semis']);
});

// ── Entries that cannot be imported ─────────────────────────────────────

test('one bad entry among good ones costs only itself, and is named with its reason', () => {
  const tooMany = Array.from({ length: 51 }, (_, i) => ({ ticker: `T${i}`, weight: 1 }));
  const plan = planImport([], envelope([
    saved({ id: 'good-1', name: 'Good one' }),
    saved({ id: 'big', name: 'Too big', holdings: tooMany }),
    saved({ id: 'good-2', name: 'Good two' }),
  ]));
  expect(plan.error).toBeNull();
  expect(plan.added.map(p => p.name)).toEqual(['Good one', 'Good two']);
  expect(plan.failed).toHaveLength(1);
  expect(plan.failed[0].name).toBe('Too big');
  expect(plan.failed[0].reason).toMatch(/more than 50/);
});

test('exactly 50 holdings is allowed', () => {
  const fifty = Array.from({ length: 50 }, (_, i) => ({ ticker: `T${i}`, weight: 2 }));
  const plan = planImport([], envelope([saved({ holdings: fifty })]));
  expect(plan.failed).toEqual([]);
  expect(plan.added).toHaveLength(1);
});

test('a ticker held twice is refused, whatever its case', () => {
  const plan = planImport([], envelope([
    saved({ holdings: [{ ticker: 'NVDA', weight: 50 }, { ticker: ' nvda ', weight: 50 }] }),
    saved({ id: 'ok', name: 'Fine' }),
  ]));
  expect(plan.added.map(p => p.name)).toEqual(['Fine']);
  expect(plan.failed).toHaveLength(1);
  expect(plan.failed[0].reason).toMatch(/NVDA twice/);
});

test.each([
  ['a path', '../etc/passwd'],
  ['a script', '<script>'],
  ['something far too long', 'A'.repeat(40)],
  ['a symbol with a space in it', 'BR K'],
])('%s is not a ticker symbol', (_label, ticker) => {
  const plan = planImport([], envelope([
    saved({ holdings: [{ ticker, weight: 100 }] }),
    saved({ id: 'ok', name: 'Fine' }),
  ]));
  expect(plan.added.map(p => p.name)).toEqual(['Fine']);
  expect(plan.failed[0].reason).toMatch(/not a ticker symbol/);
});

test('symbols with a dot or a dash, as some funds use, are tickers', () => {
  const plan = planImport([], envelope([
    saved({ holdings: [{ ticker: 'BRK.B', weight: 50 }, { ticker: 'RDS-A', weight: 50 }] }),
  ]));
  expect(plan.failed).toEqual([]);
  expect(plan.added).toHaveLength(1);
});

test('an entry that is not a portfolio at all is named by its position', () => {
  const plan = planImport([], envelope([saved({ name: 'Fine' }), 7, { value: 1 }]));
  expect(plan.added.map(p => p.name)).toEqual(['Fine']);
  expect(plan.failed.map(f => f.name)).toEqual(['Entry 2', 'Entry 3']);
  for (const failure of plan.failed) expect(failure.reason).toBeTruthy();
});

test('a failed entry does not make its name unavailable to a later one', () => {
  const tooMany = Array.from({ length: 51 }, (_, i) => ({ ticker: `T${i}`, weight: 1 }));
  const plan = planImport([], envelope([
    saved({ id: 'big', name: 'Semis', holdings: tooMany }),
    saved({ id: 'ok', name: 'Semis' }),
  ]));
  expect(plan.added.map(p => p.name)).toEqual(['Semis']);
  expect(plan.renamed).toEqual([]);
});

// A portfolio pays in or draws out, never both (#150, ADR 0002). Migration
// answers a record with both by dropping both, which would import it
// quietly as a lump sum - so the entry is held to the rule before it is
// migrated, and named, the way any other entry this app could not have made
// is.

/** An entry as a hand-edited file could hold it: both schedules, which
 *  `saved()` cannot build because it goes through the migration. */
function withBothSchedules(overrides = {}) {
  return {
    ...saved(),
    contribution: { amount: 100, frequency: 'monthly' },
    withdrawal: { amount: 500, frequency: 'monthly' },
    ...overrides,
  };
}

test('an entry with both a contribution and a withdrawal is skipped, and says why', () => {
  const plan = planImport([], envelope([withBothSchedules(), saved({ id: 'b', name: 'Energy' })]));
  expect(plan.error).toBeNull();
  expect(plan.added.map(p => p.name)).toEqual(['Energy']);
  expect(plan.failed).toHaveLength(1);
  expect(plan.failed[0].name).toBe('Semis');
  expect(plan.failed[0].reason).toMatch(/contribution/i);
  expect(plan.failed[0].reason).toMatch(/withdrawal/i);
});

test('an unusable schedule beside a good one is not "both"', () => {
  const plan = planImport([], envelope([
    withBothSchedules({ contribution: { amount: 0, frequency: 'monthly' } }),
  ]));
  expect(plan.failed).toEqual([]);
  expect(plan.added[0].withdrawal).toEqual({ amount: 500, frequency: 'monthly' });
});

test('a file whose only entry has both schedules is refused, with the reason', () => {
  const plan = planImport([saved()], envelope([withBothSchedules({ name: 'Energy', id: 'b' })]));
  expect(plan.error).toMatch(/none of the portfolios/i);
  expect(plan.added).toEqual([]);
  expect(plan.failed[0].reason).toMatch(/withdrawal/i);
});

test('an entry skipped for having both does not make its name unavailable', () => {
  const plan = planImport([], envelope([
    withBothSchedules(),
    saved({ id: 'ok', name: 'Semis' }),
  ]));
  expect(plan.added.map(p => p.name)).toEqual(['Semis']);
  expect(plan.renamed).toEqual([]);
});

// ── Export ──────────────────────────────────────────────────────────────

test('what a library exports comes back unchanged into an empty one', () => {
  const library = [
    saved(),
    saved({
      id: 'b',
      name: 'Energy',
      contribution: { amount: 100, frequency: 'yearly' },
      source: { kind: 'portfolio', id: 'a', name: 'Semis' },
      extra: { kept: true },
    }),
    saved({ id: 'c', name: 'Empty', holdings: [] }),
    saved({ id: 'd', name: 'Drawn on', withdrawal: { amount: 500, frequency: 'monthly' } }),
  ];
  const plan = planImport([], exportLibrary(library).text);
  expect(plan.error).toBeNull();
  expect(plan.added).toEqual(library);
  expect(plan.renamed).toEqual([]);
  expect(plan.skipped).toEqual([]);
  expect(plan.failed).toEqual([]);
});

test('a single portfolio exports as a Backup of one, through the same door', () => {
  const only = saved({ id: 'b', name: 'Energy' });
  const plan = planImport([saved()], exportOne(only).text);
  expect(plan.added).toEqual([only]);
});

test('the file names its format and when it was written', () => {
  const now = new Date(Date.UTC(2026, 8, 19, 9, 30));
  const parsed = JSON.parse(exportLibrary([saved()], now).text);
  expect(parsed.format).toBe(BACKUP_FORMAT);
  expect(parsed.exportedAt).toBe('2026-09-19T09:30:00.000Z');
  expect(Array.isArray(parsed.portfolios)).toBe(true);
  expect(Object.keys(parsed).sort()).toEqual(['exportedAt', 'format', 'portfolios']);
});

const NOON = new Date(2026, 8, 19, 12, 0, 0);

test('a library file is named for what it is and the day it was made', () => {
  expect(exportLibrary([saved()], NOON).filename).toBe('ma-portfolios-2026-09-19.json');
});

test('a single portfolio file is named after the portfolio', () => {
  expect(exportOne(saved({ name: 'Semis, equal weight!' }), NOON).filename)
    .toBe('ma-semis-equal-weight-2026-09-19.json');
});

test.each([
  ['characters a filesystem refuses', 'a/b\\c:d*e?f"g<h>i|j', 'ma-a-b-c-d-e-f-g-h-i-j-2026-09-19.json'],
  ['accents', 'Épargne à long terme', 'ma-epargne-a-long-terme-2026-09-19.json'],
  ['nothing usable at all', '***', 'ma-portfolio-2026-09-19.json'],
  ['a name in another script', '半導体', 'ma-portfolio-2026-09-19.json'],
])('a name with %s still gives a usable filename', (_label, name, expected) => {
  expect(exportOne(saved({ name }), NOON).filename).toBe(expected);
});

test('a very long name is cut short, and not in the middle of a hyphen', () => {
  const { filename } = exportOne(saved({ name: `${'word '.repeat(30)}end` }), NOON);
  const slug = filename.slice('ma-'.length, -'-2026-09-19.json'.length);
  expect(slug.length).toBeLessThanOrEqual(40);
  expect(slug).not.toMatch(/-$/);
  expect(slug).toMatch(/^word-word/);
});
