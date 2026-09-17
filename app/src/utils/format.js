export function fmtCorr(v) {
  if (v >= 0.995) return '1.00';
  return v.toFixed(2).replace(/^(-?)0\./, '$1.');
}

export function fmtMoney(b) {
  if (b >= 1000) return '$' + (b / 1000).toFixed(2) + 'T';
  if (b >= 1) return '$' + b.toFixed(1) + 'B';
  return '$' + Math.round(b * 1000) + 'M';
}

export function fmtPrice(v) {
  return '$' + v.toFixed(2);
}

const USD0 = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

/** A dollar figure with no cents — HoldingsTable's VALUE/GAIN/INCOME
 *  columns and HoldingChartPopup's header share this exact formatting. */
export function fmtUSD0(v) {
  return USD0.format(v);
}
