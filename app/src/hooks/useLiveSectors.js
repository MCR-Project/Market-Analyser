import { useMemo } from 'react';
import { useFetch } from './useFetch';
import { api } from '../utils/api';

/** Shape returned before live data has arrived, or if the fetch never resolves. */
const EMPTY = { sectorWeights: {}, topSector: null, ranking: [], sectorLabel: 'TOP SECTOR', sectorCounts: {} };

/**
 * Fetches the sector weight breakdown for an ETF's holdings.
 *
 * Returns EMPTY placeholders while the request is in flight or if it
 * settles without live data — consumers should check `loading`/`isLive`
 * and render a loading indicator rather than assume the fields (in
 * particular `topSector`, which is `null` until live) are populated.
 */
export function useLiveSectors(etfId) {
  const { data, loading, error } = useFetch(
    () => api.getSectors(etfId),
    [etfId],
    { fallback: null }
  );

  const isLive = !!data?.sectors?.length;

  const result = useMemo(() => {
    if (!isLive) return EMPTY;
    const topSec = data.topSector || data.sectors[0];
    return {
      sectorWeights: Object.fromEntries(data.sectors.map(s => [s.name, s.weight])),
      topSector: {
        name: topSec.name,
        tag: topSec.tag,
        weight: topSec.weight,
        share: topSec.share,
      },
      ranking: data.sectors.slice(0, 5).map(s => ({
        tag: s.tag,
        share: s.share + '%',
        barWidth: Math.round((s.weight / (topSec.weight || 1)) * 100),
      })),
      sectorLabel: data.sectorLabel || 'TOP SECTOR',
      sectorCounts: Object.fromEntries(data.sectors.map(s => [s.name, s.count])),
    };
  }, [data, isLive]);

  return { ...result, loading, error, isLive };
}
