import { describe, it, expect } from 'vitest';
import { fullViewPath, normalViewPath, parseFullViewPath, dashboardPathOf } from './fullViewRoute';

describe('fullViewPath / normalViewPath', () => {
  it('are the two pages of one fund and kind', () => {
    expect(fullViewPath('SPY', 'matrix')).toBe('/etf/SPY/full/matrix');
    expect(fullViewPath('SPY', 'network')).toBe('/etf/SPY/full/network');
    expect(normalViewPath('SPY', 'network')).toBe('/etf/SPY/network');
  });
});

describe('parseFullViewPath', () => {
  it('reads the fund and kind off a Full view URL', () => {
    expect(parseFullViewPath('/etf/SPY/full/matrix')).toEqual({ etfId: 'SPY', kind: 'matrix' });
    expect(parseFullViewPath('/etf/smh/full/network')).toEqual({ etfId: 'smh', kind: 'network' });
  });

  it('is null for anything else, including a Full view of a kind that does not exist', () => {
    expect(parseFullViewPath('/etf/SPY/matrix')).toBeNull();
    expect(parseFullViewPath('/etf/SPY/full/table')).toBeNull();
    expect(parseFullViewPath('/etf/SPY/full')).toBeNull();
    expect(parseFullViewPath('/etf/SPY/full/matrix/extra')).toBeNull();
    expect(parseFullViewPath('/stock/AAPL')).toBeNull();
  });
});

describe('dashboardPathOf', () => {
  it('is the path itself, with its query, for a dashboard URL', () => {
    expect(dashboardPathOf('/etf/SPY/matrix', '?matrixOrder=alpha')).toBe('/etf/SPY/matrix?matrixOrder=alpha');
  });

  it('is the normal view of the same fund and kind for a Full view, so the Analyser tab does not lead back to a Full view', () => {
    expect(dashboardPathOf('/etf/SPY/full/network', '?threshold=0.5')).toBe('/etf/SPY/network');
  });

  it('is null off the dashboard', () => {
    expect(dashboardPathOf('/docs', '')).toBeNull();
    expect(dashboardPathOf('/stock/AAPL', '')).toBeNull();
  });
});
