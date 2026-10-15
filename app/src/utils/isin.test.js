/**
 * looksLikeIsin — the seam the ISIN path of the ticker search is tested at
 * (issue #191): is what is in the box shaped like an ISIN, so that the ISIN
 * endpoint is asked instead of the as-you-type search.
 *
 * Shape only. The check digit is the backend's to judge (issue #190), so a
 * code of the right shape with a wrong digit is still "looks like an ISIN"
 * here and gets the backend's 400 in words.
 *
 * describeIsinError is the other half: what each failure of that endpoint
 * says, which is the same wording wherever the field is used.
 *
 * Plain functions and inline data, no DOM.
 */
import { expect, test } from 'vitest';
import { describeIsinError, looksLikeIsin } from './isin';

test('a real ISIN is recognised', () => {
  expect(looksLikeIsin('US0378331005')).toBe(true);
  expect(looksLikeIsin('IE00B4L5Y983')).toBe(true);
});

test('case and surrounding spaces do not matter', () => {
  expect(looksLikeIsin('us0378331005')).toBe(true);
  expect(looksLikeIsin('  US0378331005  ')).toBe(true);
  expect(looksLikeIsin('\tie00b4l5y983\n')).toBe(true);
});

test('the shape is two letters, nine alphanumerics and one final digit', () => {
  expect(looksLikeIsin('0S0378331005')).toBe(false); // a digit where a letter belongs
  expect(looksLikeIsin('U10378331005')).toBe(false);
  expect(looksLikeIsin('US037833100X')).toBe(false); // the last character is a digit
  expect(looksLikeIsin('US03783310A5')).toBe(true); // letters are fine in the middle
});

test('anything not twelve characters long is not one', () => {
  expect(looksLikeIsin('US037833100')).toBe(false);
  expect(looksLikeIsin('US03783310055')).toBe(false);
  expect(looksLikeIsin('')).toBe(false);
  expect(looksLikeIsin('   ')).toBe(false);
});

test('a ticker or a name is not one', () => {
  expect(looksLikeIsin('AAPL')).toBe(false);
  expect(looksLikeIsin('BRK.B')).toBe(false);
  expect(looksLikeIsin('Apple Inc')).toBe(false);
});

test('spaces or punctuation inside the code are not forgiven', () => {
  expect(looksLikeIsin('US 0378331005')).toBe(false);
  expect(looksLikeIsin('US-037833100-5')).toBe(false);
});

test('a non-string is not one', () => {
  expect(looksLikeIsin(null)).toBe(false);
  expect(looksLikeIsin(undefined)).toBe(false);
});

test('a 404 says some real instruments are not indexed and points at the ticker', () => {
  expect(describeIsinError({ status: 404 }, 'US0378331005')).toBe(
    'No listing found for this ISIN — some real instruments are not indexed; try its ticker symbol.'
  );
});

test('a 400 says the code is not a valid ISIN and to check how it was typed', () => {
  expect(describeIsinError({ status: 400 }, 'US0378331006')).toBe(
    'This is not a valid ISIN — check how it was typed.'
  );
});

test('anything else is the existing "could not be checked just now" copy, naming the code', () => {
  const copy = 'US0378331005 could not be checked just now — the price source did not answer.';
  expect(describeIsinError({ status: 503 }, 'US0378331005')).toBe(copy);
  expect(describeIsinError({ status: 429 }, 'US0378331005')).toBe(copy);
  expect(describeIsinError(new TypeError('Failed to fetch'), 'US0378331005')).toBe(copy);
});
