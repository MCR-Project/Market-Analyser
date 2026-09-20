/**
 * portfolioStorage — the rules for what a saved portfolio's money-flow
 * schedule may be (issue #150, ADR 0002), tested through `migratePortfolio`,
 * the one function every reader of the library goes through, and
 * `makePortfolio`, the one that mints a Duplicate or a "Save a copy".
 *
 * A portfolio pays in (a recurring contribution) or draws out (a recurring
 * withdrawal), never both. The library is the reader that *salvages*, and
 * a schedule it cannot make sense of is no schedule - which simulates as the
 * lump sum it always did - rather than a guess at which of two the person
 * meant. The other two readers have their own rules (a link refuses, a Backup
 * skips the entry), and their own test files.
 *
 * Plain functions and inline data: nothing here touches storage or the page.
 */
import { expect, test } from 'vitest';
import { makePortfolio, migratePortfolio, scheduleFields } from './portfolioStorage';

const BASE = {
  id: 'a',
  name: 'Semis',
  value: 10000,
  holdings: [{ ticker: 'NVDA', weight: 100 }],
};

test('a recurring withdrawal comes through migration unchanged', () => {
  const migrated = migratePortfolio({ ...BASE, withdrawal: { amount: 500, frequency: 'monthly' } });
  expect(migrated.withdrawal).toEqual({ amount: 500, frequency: 'monthly' });
  expect(migrated.contribution).toBeUndefined();
});

test('a portfolio with neither schedule has neither', () => {
  const migrated = migratePortfolio(BASE);
  expect(migrated.withdrawal).toBeUndefined();
  expect(migrated.contribution).toBeUndefined();
});

test('a recurring contribution is still read as before', () => {
  const migrated = migratePortfolio({ ...BASE, contribution: { amount: 250, frequency: 'yearly' } });
  expect(migrated.contribution).toEqual({ amount: 250, frequency: 'yearly' });
  expect(migrated.withdrawal).toBeUndefined();
});

test.each([
  ['no frequency', { amount: 500 }],
  ['a frequency this build does not have', { amount: 500, frequency: 'weekly' }],
  ['a zero amount', { amount: 0, frequency: 'monthly' }],
  ['a negative amount', { amount: -500, frequency: 'monthly' }],
  ['an amount that is not a number', { amount: '500', frequency: 'monthly' }],
  ['something that is not an object', 500],
])('a withdrawal with %s is no schedule, not a guess', (_label, withdrawal) => {
  expect(migratePortfolio({ ...BASE, withdrawal }).withdrawal).toBeUndefined();
});

test('a record with both schedules has neither, and neither is preferred', () => {
  // Only reachable through a hand-edited library or a build that allowed it.
  // Keeping one would quietly change the numbers of a portfolio whose owner
  // never chose to; dropping both is the same answer as any other schedule
  // that cannot be read.
  const migrated = migratePortfolio({
    ...BASE,
    contribution: { amount: 100, frequency: 'monthly' },
    withdrawal: { amount: 500, frequency: 'monthly' },
  });
  expect(migrated.contribution).toBeUndefined();
  expect(migrated.withdrawal).toBeUndefined();
});

test('an unusable schedule beside a good one does not make it "both"', () => {
  const migrated = migratePortfolio({
    ...BASE,
    contribution: { amount: 0, frequency: 'monthly' },
    withdrawal: { amount: 500, frequency: 'monthly' },
  });
  expect(migrated.withdrawal).toEqual({ amount: 500, frequency: 'monthly' });
  expect(migrated.contribution).toBeUndefined();
});

// What goes to the simulator: the request is built field by field, and a
// portfolio with no schedule must key the same request it always did.

test('the request carries the withdrawal a portfolio has, and only that', () => {
  const withdrawal = { amount: 500, frequency: 'monthly' };
  expect(scheduleFields({ ...BASE, withdrawal })).toEqual({ withdrawal });
});

test('the request carries the contribution a portfolio has, and only that', () => {
  const contribution = { amount: 250, frequency: 'yearly' };
  expect(scheduleFields({ ...BASE, contribution })).toEqual({ contribution });
});

test('a portfolio with no schedule adds nothing to the request, not a null', () => {
  expect(scheduleFields(BASE)).toEqual({});
  expect(Object.keys(scheduleFields(BASE))).toEqual([]);
  expect(scheduleFields(undefined)).toEqual({});
});

test('a copy keeps the withdrawal it was seeded with', () => {
  const copy = makePortfolio({ ...BASE, withdrawal: { amount: 500, frequency: 'quarterly' } });
  expect(copy.withdrawal).toEqual({ amount: 500, frequency: 'quarterly' });
  expect(copy.contribution).toBeUndefined();
});

test('a copy seeded with both schedules has neither', () => {
  const copy = makePortfolio({
    ...BASE,
    contribution: { amount: 100, frequency: 'monthly' },
    withdrawal: { amount: 500, frequency: 'monthly' },
  });
  expect(copy.contribution).toBeUndefined();
  expect(copy.withdrawal).toBeUndefined();
});
