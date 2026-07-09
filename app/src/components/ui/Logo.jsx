/**
 * Logo — stock brand icon, resolved from the company name (not a
 * per-ticker lookup table) via utils/logo.js. Falls back from theSVG's
 * icon CDN to a guessed-domain favicon to a neutral placeholder on
 * successive load errors.
 * Props: ticker (string), name (company name, optional — the ticker is
 * slugified instead when omitted), size (px), className.
 */
import { memo } from 'react';
import { logoUrl, fallbackFaviconUrl, handleLogoError } from '../../utils/logo';

export const Logo = memo(function Logo({ ticker, name, size = 32, className = '' }) {
  const r = Math.round(size * 0.22);
  return (
    <img
      src={logoUrl(ticker, name)}
      data-favicon-fallback={fallbackFaviconUrl(ticker, name)}
      alt={ticker}
      onError={handleLogoError}
      className={`flex-none object-contain bg-[var(--bg-3)] ${className}`}
      style={{ width: size, height: size, borderRadius: r }}
    />
  );
});
