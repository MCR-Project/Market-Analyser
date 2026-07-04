/**
 * useEtfStore — global store for the currently selected ETF ticker.
 *
 * This is the single source of truth for "which ETF is active." Any
 * component can read `etfId` or call `switchEtf` directly, without it
 * being passed down through props. Data hooks (useLiveEtf, etc.) read
 * `etfId` from here instead of owning their own local selection state,
 * so every component that fetches ETF-scoped data — however deep in the
 * tree, and independently of its siblings — always agrees on which ETF
 * is selected.
 */
import { create } from 'zustand';

export const useEtfStore = create((set) => ({
  etfId: 'SPY',
  switchEtf: (id) => set({ etfId: id }),
}));
