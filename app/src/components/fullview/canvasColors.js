/**
 * canvasColors — the page's colours, resolved for a canvas (issue #173).
 *
 * A canvas cannot read CSS variables, and the page's colours are variables that
 * change with the theme (and `cellColor`'s ramp is a `color-mix()` of two of them).
 * Rather than copy the palette into JS, where it would drift from `index.css`, this
 * asks the browser: each colour is set on a hidden probe element inside the page,
 * the resolved value is read back, and a 1 × 1 canvas turns whatever syntax that
 * came back in (`rgb()`, `oklab()`, `color(srgb …)`) into bytes. The matrix's ramp
 * is `utils/correlation.js`'s own `cellColor` sampled at every whole percentage, so
 * the Full view's colours are the normal matrix's by construction.
 *
 * `useCanvasColors()` returns `[hostRef, colors]`: attach `hostRef` to an element
 * inside the page (it must be a descendant of whatever sets the theme), and `colors`
 * is null until it is mounted, then a new object each time the theme changes —
 * which is what makes a canvas repaint on a theme toggle.
 */
import { useEffect, useMemo, useState } from 'react';
import { cellColor } from '../../utils/correlation';

const TOKENS = {
  bg: 'var(--bg)', bg1: 'var(--bg-1)', bg2: 'var(--bg-2)', bg3: 'var(--bg-3)',
  fg: 'var(--fg)', fg1: 'var(--fg-1)', fg2: 'var(--fg-2)', fg3: 'var(--fg-3)',
  accent: 'var(--accent)', accentFg: 'var(--accent-fg)',
  border: 'var(--border)', borderStrong: 'var(--border-strong)',
};

function resolveColors(host) {
  const probe = document.createElement('div');
  probe.setAttribute('aria-hidden', 'true');
  probe.style.cssText = 'position:absolute;width:0;height:0;visibility:hidden;pointer-events:none';
  host.appendChild(probe);
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });

  /** `[r, g, b, a]` bytes of any CSS colour, variables and `color-mix()` included. */
  const bytes = (css) => {
    probe.style.backgroundColor = '';
    probe.style.backgroundColor = css;
    const resolved = getComputedStyle(probe).backgroundColor;
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = '#000';
    ctx.fillStyle = resolved;
    ctx.fillRect(0, 0, 1, 1);
    return Array.from(ctx.getImageData(0, 0, 1, 1).data);
  };
  const css = ([r, g, b, a]) => (a === 255 ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${(a / 255).toFixed(3)})`);

  try {
    const colors = {};
    for (const [name, value] of Object.entries(TOKENS)) colors[name] = css(bytes(value));
    colors.ramp = Array.from({ length: 101 }, (_, pct) => bytes(cellColor(pct / 100).bg).slice(0, 3));
    colors.none = bytes('var(--bg-3)').slice(0, 3);
    colors.diagonal = bytes('var(--fg-2)').slice(0, 3);
    return colors;
  } finally {
    probe.remove();
  }
}

export function useCanvasColors() {
  const [host, setHost] = useState(null);
  const [theme, setTheme] = useState(0);

  useEffect(() => {
    const observer = new MutationObserver(() => setTheme((n) => n + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);

  // `theme` is only a reason to look again: the answer is read off the page.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const colors = useMemo(() => (host ? resolveColors(host) : null), [host, theme]);
  return [setHost, colors];
}
