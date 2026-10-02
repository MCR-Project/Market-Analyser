import { expect, test } from 'vitest';
import { launchPhase, QUIET_MS, SLOW_MS } from './launchScreen';

test('a backend that answers at once never shows the screen', () => {
  expect(launchPhase(0)).toBe('quiet');
  expect(launchPhase(QUIET_MS - 1)).toBe('quiet');
});

test('past the quiet window the screen says the server is waking up', () => {
  expect(launchPhase(QUIET_MS)).toBe('waking');
  expect(launchPhase(SLOW_MS - 1)).toBe('waking');
});

test('a wait longer than a cold start stops promising one', () => {
  expect(launchPhase(SLOW_MS)).toBe('slow');
  expect(launchPhase(10 * SLOW_MS)).toBe('slow');
});
