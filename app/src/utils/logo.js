/**
 * logo.js — resolves a stock's brand icon without a hand-maintained
 * per-ticker lookup table.
 *
 * Instead of a giant ticker → domain/logo map, this slugifies the
 * company's name (already in data/stocks.js for other purposes, e.g.
 * "NVDA" -> "NVIDIA") into the slug used by theSVG's brand icon catalog
 * (https://thesvg.org — the same dataset published as the @thesvg/icons
 * npm package) and loads it from their CDN.
 *
 * @thesvg/icons itself isn't imported here: its subpaths (one file per
 * icon, e.g. `@thesvg/icons/nvidia`) are only resolvable when the exact
 * specifier is statically known at build time. Since the ticker/slug is
 * only known at runtime, a dynamically-computed bare specifier like
 * `@thesvg/icons/${slug}` can't be resolved by the browser or bundled by
 * Rollup — confirmed by testing it directly (fails with "Failed to
 * resolve module specifier"). Their CDN serves the identical SVGs by
 * slug over plain HTTP, which works for any computed name with no
 * bundler involvement, so that's what's used here.
 *
 * A tiny override table covers the handful of names whose real slug
 * doesn't match a plain slugify of the company name. Everything else is
 * resolved on the fly — no per-ticker entry needed as new holdings show up.
 */

const SUFFIX_WORDS = new Set([
  'inc', 'incorporated', 'corp', 'corporation', 'co', 'company',
  'ltd', 'limited', 'llc', 'plc', 'group', 'holdings', 'platforms',
  'technologies', 'technology', 'the',
]);

// Only for tickers whose real theSVG slug doesn't match slugify(name), or
// (for JPM) whose plain slugify doesn't match the guessed favicon domain
// used as a second-chance fallback when theSVG has no icon for the name.
const SLUG_OVERRIDES = {
  GOOGL: 'google',            // trades as Alphabet, brand icon is filed under "google"
  'BRK.B': 'berkshirehathaway',
  TSM: 'tsmc',
  JPM: 'jpmorganchase',       // "JPMorgan Chase" slugifies with a hyphen; the real domain has none
};

function slugify(name) {
  return name
    .normalize('NFD').replace(/[̀-ͯ]/g, '') // strip accents, e.g. Nestlé -> Nestle
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9\s-]/g, '')
    .split(/\s+/)
    .filter(word => word && !SUFFIX_WORDS.has(word))
    .join('-');
}

/** Resolves a ticker + company name to the slug used by thesvg.org. */
export function resolveIconSlug(ticker, name) {
  return SLUG_OVERRIDES[ticker] || slugify(name || ticker);
}

const LOGO_FALLBACK = 'data:image/svg+xml;base64,' + btoa(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#e2e4e9"/></svg>'
);

/** Primary source: theSVG's brand icon CDN, resolved by name. */
export function logoUrl(ticker, name) {
  return `https://thesvg.org/icons/${resolveIconSlug(ticker, name)}/default.svg`;
}

/** Second-chance source if the theSVG icon 404s: guess the company's domain from the same slug. */
export function fallbackFaviconUrl(ticker, name) {
  return `https://www.google.com/s2/favicons?sz=128&domain_url=https://${resolveIconSlug(ticker, name)}.com`;
}

/** Two-stage <img onError> handler: theSVG icon -> guessed-domain favicon -> neutral placeholder. */
export function handleLogoError(e) {
  const el = e.target;
  if (!el.dataset.logoStage) {
    el.dataset.logoStage = 'favicon';
    el.src = el.dataset.faviconFallback || LOGO_FALLBACK;
  } else {
    el.onerror = null;
    el.src = LOGO_FALLBACK;
  }
}

/** Same two-stage fallback for SVG <image> elements (NetworkView's node patterns). */
export function handleSvgImageLogoError(e) {
  const el = e.target;
  if (!el.dataset.logoStage) {
    el.dataset.logoStage = 'favicon';
    el.setAttribute('href', el.dataset.faviconFallback || LOGO_FALLBACK);
  } else {
    el.removeAttribute('href');
  }
}
