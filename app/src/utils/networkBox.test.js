import { expect, test } from 'vitest';
import { NETWORK_ASPECT, NETWORK_MAX_MIN_HEIGHT, networkMinHeight } from './networkBox';

test('the graph is at least 0.85 of its width tall, so it reads closer to a square than a strip', () => {
  expect(networkMinHeight(800)).toBe(Math.ceil(800 * NETWORK_ASPECT));
  expect(networkMinHeight(800)).toBe(680);
});

test('a wider box asks for a taller one, up to the cap', () => {
  expect(networkMinHeight(600)).toBeLessThan(networkMinHeight(700));
});

test('a very wide box is capped, so a wide screen does not make a page-tall graph', () => {
  expect(networkMinHeight(2000)).toBe(NETWORK_MAX_MIN_HEIGHT);
  expect(networkMinHeight(1060)).toBe(NETWORK_MAX_MIN_HEIGHT);
});

test('a fractional result rounds up, never down', () => {
  expect(networkMinHeight(501)).toBe(Math.ceil(501 * NETWORK_ASPECT));
});

test('before the box is measured there is nothing to ask for', () => {
  expect(networkMinHeight(0)).toBe(0);
  expect(networkMinHeight(NaN)).toBe(0);
  expect(networkMinHeight(-5)).toBe(0);
});
