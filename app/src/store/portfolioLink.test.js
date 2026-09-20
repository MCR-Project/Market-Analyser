/**
 * portfolioLink — a Share Link's payload, tested through the two public
 * functions that write and read it: `encodePortfolio` and `decodePortfolio`
 * (issue #150 is what added this file; the link module had no tests before
 * it, and the withdrawal is the first field whose absence from an older
 * reader would silently change what a link shows).
 *
 * The payload carries its own version, independent of the storage schema,
 * because it is a wire format other people's browsers have to read. Version 3
 * added the recurring withdrawal (`w`); versions 1 and 2 must keep reading,
 * and a payload with both a contribution (`c`) and a withdrawal is refused
 * whole - a link is untrusted input, and showing somebody a different
 * portfolio than the sender's is worse than an error (ADR 0002).
 *
 * Plain functions and inline data. Payloads are hand-made with the web's own
 * `btoa`/`atob` so the tests do not use the module's own encoder to build the
 * input they hold its decoder to.
 */
import { expect, test } from 'vitest';
import { decodePortfolio, encodePortfolio } from './portfolioLink';

const PORTFOLIO = {
  name: 'Semis',
  value: 10000,
  rebalance: 'none',
  holdings: [{ ticker: 'NVDA', weight: 60 }, { ticker: 'AMD', weight: 40 }],
};

/** A payload as somebody else's build would have written it. Every value
 *  here is ASCII, so `btoa` alone is enough. */
function payload(fields) {
  return btoa(JSON.stringify(fields)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** What a payload actually says, without going through the decoder. */
function contents(encoded) {
  const base64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
  return JSON.parse(atob(base64 + '='.repeat((4 - (base64.length % 4)) % 4)));
}

const V3 = { v: 3, n: 'Semis', a: 10000, r: 'none', h: [['NVDA', 100]] };

// ── Writing ─────────────────────────────────────────────────────────────

test('a new link is version 3, whatever it carries', () => {
  expect(contents(encodePortfolio(PORTFOLIO)).v).toBe(3);
  expect(contents(encodePortfolio({ ...PORTFOLIO, withdrawal: { amount: 500, frequency: 'monthly' } })).v).toBe(3);
});

test('a withdrawal travels as `w`, and nothing is written for one that is not there', () => {
  const withdrawing = contents(encodePortfolio({
    ...PORTFOLIO,
    withdrawal: { amount: 500, frequency: 'monthly' },
  }));
  expect(withdrawing.w).toEqual([500, 'monthly']);
  expect(withdrawing).not.toHaveProperty('c');

  // The common link stays the length it was.
  const plain = contents(encodePortfolio(PORTFOLIO));
  expect(plain).not.toHaveProperty('w');
  expect(plain).not.toHaveProperty('c');
});

// ── Round trips ─────────────────────────────────────────────────────────

test('a portfolio with a withdrawal is the same portfolio on the other side', () => {
  const withdrawal = { amount: 500, frequency: 'quarterly' };
  const { portfolio, error } = decodePortfolio(encodePortfolio({ ...PORTFOLIO, withdrawal }));
  expect(error).toBeNull();
  expect(portfolio).toEqual({ ...PORTFOLIO, withdrawal, contribution: undefined });
});

test('a portfolio with a contribution still is', () => {
  const contribution = { amount: 250, frequency: 'monthly' };
  const { portfolio, error } = decodePortfolio(encodePortfolio({ ...PORTFOLIO, contribution }));
  expect(error).toBeNull();
  expect(portfolio.contribution).toEqual(contribution);
  expect(portfolio.withdrawal).toBeUndefined();
});

test('a portfolio with no schedule has none on the other side', () => {
  const { portfolio, error } = decodePortfolio(encodePortfolio(PORTFOLIO));
  expect(error).toBeNull();
  expect(portfolio.contribution).toBeUndefined();
  expect(portfolio.withdrawal).toBeUndefined();
});

// ── Older links keep working ────────────────────────────────────────────

test('a version 1 link, from before contributions, still opens', () => {
  const { portfolio, error } = decodePortfolio(payload({ ...V3, v: 1 }));
  expect(error).toBeNull();
  expect(portfolio.name).toBe('Semis');
  expect(portfolio.contribution).toBeUndefined();
  expect(portfolio.withdrawal).toBeUndefined();
});

test('a version 2 link, with a contribution, still opens', () => {
  const { portfolio, error } = decodePortfolio(payload({ ...V3, v: 2, c: [250, 'monthly'] }));
  expect(error).toBeNull();
  expect(portfolio.contribution).toEqual({ amount: 250, frequency: 'monthly' });
  expect(portfolio.withdrawal).toBeUndefined();
});

test('a link from a newer build is told apart from a broken one', () => {
  const { portfolio, error } = decodePortfolio(payload({ ...V3, v: 4 }));
  expect(portfolio).toBeNull();
  expect(error).toMatch(/newer version/i);
});

// ── Refusing what cannot be read ────────────────────────────────────────

test('a link carrying both a contribution and a withdrawal is refused whole', () => {
  const { portfolio, error } = decodePortfolio(payload({
    ...V3,
    c: [100, 'monthly'],
    w: [500, 'monthly'],
  }));
  expect(portfolio).toBeNull();
  expect(error).toMatch(/contribution/i);
  expect(error).toMatch(/withdrawal/i);
  expect(error).toMatch(/fresh link/i);
});

test.each([
  ['not a pair', [500]],
  ['not a list', { amount: 500, frequency: 'monthly' }],
  ['an amount that is a string', ['500', 'monthly']],
  ['an amount of zero', [0, 'monthly']],
  ['a negative amount', [-500, 'monthly']],
  ['an amount beyond any real one', [1e13, 'monthly']],
  ['a frequency this build does not have', [500, 'weekly']],
])('a withdrawal that is %s is refused rather than dropped', (_label, w) => {
  const { portfolio, error } = decodePortfolio(payload({ ...V3, w }));
  expect(portfolio).toBeNull();
  expect(error).toMatch(/withdraw/i);
});

test('a null withdrawal is no withdrawal', () => {
  const { portfolio, error } = decodePortfolio(payload({ ...V3, w: null }));
  expect(error).toBeNull();
  expect(portfolio.withdrawal).toBeUndefined();
});
