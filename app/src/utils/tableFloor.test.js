import { expect, test } from 'vitest';
import { ESTIMATED_ROW_HEIGHT, FLOOR_ROWS, tableFloor } from './tableFloor';

const table = { chrome: 200, gap: 6, padding: 30 };

test('the floor is the chrome, the rows box padding, five rows and the gaps between them', () => {
  // 200 + 30 + 5 × 86 + 4 × 6
  expect(tableFloor({ ...table, rowHeight: 86 })).toBe(684);
});

test('a taller row raises the floor, so wrapped metric columns still leave five holdings', () => {
  const plain = tableFloor({ ...table, rowHeight: 86 });
  const wrapped = tableFloor({ ...table, rowHeight: 140 });
  expect(wrapped - plain).toBe(FLOOR_ROWS * (140 - 86));
});

test('before any row has been drawn the floor uses the estimated row height', () => {
  const estimated = tableFloor({ ...table, rowHeight: null });
  expect(estimated).toBe(tableFloor({ ...table, rowHeight: ESTIMATED_ROW_HEIGHT }));
  expect(tableFloor({ ...table, rowHeight: 0 })).toBe(estimated);
});

test('a fractional measurement rounds the floor up, never down', () => {
  expect(tableFloor({ chrome: 200.2, gap: 6, padding: 30, rowHeight: 86 })).toBe(685);
});

test('the number of rows can be asked for', () => {
  expect(tableFloor({ ...table, rowHeight: 86, rows: 1 })).toBe(200 + 30 + 86);
});
