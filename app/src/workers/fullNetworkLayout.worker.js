/**
 * The Full view's network layout, off the page's thread (issue #173): ~125,000
 * pairs × 400 iterations is most of a second, and on the main thread that is a
 * tab that cannot scroll or repaint while it runs. The work is
 * `utils/fullNetworkLayout.js`; this only carries the input in and the positions
 * out. `hooks/useFullNetworkLayout.js` is the other half.
 */
import { layoutFullNetwork } from '../utils/fullNetworkLayout';

self.onmessage = (event) => {
  const { xs, ys } = layoutFullNetwork(event.data);
  self.postMessage({ xs, ys }, [xs.buffer, ys.buffer]);
};
