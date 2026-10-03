/**
 * useFullNetworkLayout — the Full view's network node positions, computed once per
 * result (issue #173), in a worker so the page stays alive while it runs.
 *
 * Returns `{ positions, error }`: `positions` is `{ xs, ys }` in the graph's own
 * world (`NETWORK_WORLD`), null while it is being worked out, and the page shows
 * that. A new result (another fund, or the same fund deep-filled again) starts a new
 * layout and never shows the last one's. If a worker cannot be made or fails to
 * load, the same function runs on the page's own thread after a tick — slower and
 * briefly blocking, but a graph, not a blank.
 *
 * The Link Threshold is not an input: nothing in the layout reads it, which is what
 * keeps the nodes still while it is dragged.
 */
import { useEffect, useState } from 'react';
import { layoutFullNetwork } from '../utils/fullNetworkLayout';

export function useFullNetworkLayout(fund) {
  const key = `${fund.etfId}:${fund.asOf}`;
  const [state, setState] = useState({ key: null, positions: null, error: null });

  useEffect(() => {
    let cancelled = false;
    let worker = null;
    const input = { corr: fund.corr, n: fund.n, weights: fund.weights };
    const done = (positions) => { if (!cancelled) setState({ key, positions, error: null }); };
    const failed = (error) => { if (!cancelled) setState({ key, positions: null, error }); };
    const inline = () => setTimeout(() => {
      try { done(layoutFullNetwork(input)); } catch (error) { failed(error); }
    }, 0);

    try {
      worker = new Worker(new URL('../workers/fullNetworkLayout.worker.js', import.meta.url), { type: 'module' });
      worker.onmessage = (event) => done(event.data);
      worker.onerror = () => { worker.terminate(); inline(); };
      worker.postMessage(input);
    } catch {
      inline();
    }
    return () => {
      cancelled = true;
      worker?.terminate();
    };
  }, [fund, key]);

  return state.key === key ? { positions: state.positions, error: state.error } : { positions: null, error: null };
}
