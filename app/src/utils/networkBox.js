/**
 * networkBox — how tall the network graph's box must be for its width
 * (issue #176).
 *
 * The graph takes whatever height the view has left below the ETF card, and
 * inside a scrolling page that can be very little: on a short window every
 * node was squeezed onto one horizontal line. The width is not the problem —
 * it is whatever the panel beside the Details gets — so the floor is a share
 * of that width: close to a square, never a strip.
 *
 * A floor, not a size: a tall window still gives the graph all the height it
 * has. Capped, because the panel can be two thousand pixels wide on a large
 * screen, and a graph as tall as it is wide there is a page to scroll through
 * rather than a picture. Past the cap the nodes have room to spread anyway.
 */

/** Height over width the graph never drops below. 0.85, not 1: a little
 *  wider than tall still looks like a square, and costs less scrolling. */
export const NETWORK_ASPECT = 0.85;

/** The most the floor ever asks for, in pixels. */
export const NETWORK_MAX_MIN_HEIGHT = 900;

/** The minimum height for a box `width` pixels wide, or 0 before the box has
 *  been measured (a width of 0), so the floor is never a made-up number. */
export function networkMinHeight(width) {
  if (!(width > 0)) return 0;
  return Math.min(NETWORK_MAX_MIN_HEIGHT, Math.ceil(width * NETWORK_ASPECT));
}
