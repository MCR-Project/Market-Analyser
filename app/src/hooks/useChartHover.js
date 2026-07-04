/**
 * useChartHover — manages hover state for AreaChart.
 *
 * Converts mouse X position to a data index, then builds a tooltip
 * object with the date label, return %, period delta, and raw value.
 *
 * The date label comes solely from the `dates` array (ISO strings from
 * the API) — no mock/computed label fallback.
 */
import { useState, useCallback } from 'react';
import { fmtMoney } from '../utils/format';

const W = 360, PAD = 4;

export function useChartHover(arr, timeframe, dates = null) {
  const [hoverIdx, setHoverIdx] = useState(null);
  const len = arr?.length ?? 0;

  const onMouseMove = useCallback((e) => {
    if (!len) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width;
    const i = Math.round(
      Math.max(0, Math.min(1, (relX * W - PAD) / (W - 2 * PAD))) * (len - 1)
    );
    setHoverIdx(prev => prev === i ? prev : i);
  }, [len]);

  const onMouseLeave = useCallback(() => {
    setHoverIdx(null);
  }, []);

  let tooltip = null;
  if (arr && hoverIdx != null && arr[hoverIdx] !== undefined) {
    const val = arr[hoverIdx];
    const prevVal = hoverIdx > 0 ? arr[hoverIdx - 1] : null;
    const delta = prevVal != null ? ((val - prevVal) / prevVal * 100) : null;
    const deltaPos = delta != null ? delta >= 0 : null;
    const runReturn = ((val / arr[0]) - 1) * 100;
    const runPos = runReturn >= 0;
    const pctX = (PAD + (hoverIdx / Math.max(1, len - 1)) * (W - 2 * PAD)) / W * 100;

    const label = dates && dates[hoverIdx] ? formatDate(dates[hoverIdx]) : '';

    tooltip = {
      label,
      rawValue: val,
      formattedValue: fmtMoney(val),
      returnPct: (runPos ? '+' : '') + runReturn.toFixed(2) + '%',
      runPos,
      deltaPos,
      pctX,
      alignRight: pctX >= 55,
    };
  }

  return { hoverIdx, onMouseMove, onMouseLeave, tooltip };
}

function formatDate(isoDate) {
  const d = new Date(isoDate + 'T00:00:00');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
}
