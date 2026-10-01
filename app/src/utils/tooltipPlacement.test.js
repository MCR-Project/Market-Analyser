import { expect, test } from 'vitest';
import { FLIP_AT, TOOLTIP_GAP, tooltipPlacement } from './tooltipPlacement';

test('left of the middle the tooltip sits to the right of the line, a gap away from it', () => {
  expect(tooltipPlacement({ pctX: 30 })).toEqual({ left: `calc(30% + ${TOOLTIP_GAP}px)` });
});

test('past the middle it sits to the left of the line, a gap away from it', () => {
  // Pinned by its right edge: 100% - 70% of the box is to the right of the line.
  expect(tooltipPlacement({ pctX: 70 })).toEqual({ right: `calc(30% + ${TOOLTIP_GAP}px)` });
});

test('the flip is at FLIP_AT: just under it is on the right of the line, at it on the left', () => {
  expect(tooltipPlacement({ pctX: FLIP_AT - 1 })).toHaveProperty('left');
  expect(tooltipPlacement({ pctX: FLIP_AT })).toHaveProperty('right');
});

test('it is never pinned on both sides at once, so it keeps its own width', () => {
  for (const pctX of [0, 10, 54.9, 55, 90, 100]) {
    expect(Object.keys(tooltipPlacement({ pctX }))).toHaveLength(1);
  }
});

test('a clearance moves the near edge away from the line by that share of the width', () => {
  // A candle's slot is shaded half a slot either side of its centre.
  expect(tooltipPlacement({ pctX: 20, clearPct: 5 })).toEqual({ left: `calc(25% + ${TOOLTIP_GAP}px)` });
  expect(tooltipPlacement({ pctX: 80, clearPct: 5 })).toEqual({ right: `calc(25% + ${TOOLTIP_GAP}px)` });
});
