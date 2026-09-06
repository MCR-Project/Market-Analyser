/**
 * useLiveStatus — lets whichever page owns the live data tell the shared
 * Header whether the backend is answering.
 *
 * The header outlives the pages under it, but the connectivity badge it
 * shows is the dashboard's fact: it means "ETF and correlation data
 * loaded". Rather than have the layout fetch that itself — which would
 * pull an ETF request onto every page, documentation included — the
 * dashboard publishes what it already knows, and the badge simply does
 * not render on pages that publish nothing.
 */
import { createContext, useContext, useEffect } from 'react';

export const LiveStatusContext = createContext(null);

/** Read the published status. `undefined` means "no page is claiming one". */
export function useLiveStatus() {
  return useContext(LiveStatusContext)?.isLive;
}

/**
 * Publish this page's connectivity while it is mounted, and withdraw it
 * on the way out so a stale badge never outlives the page that meant it.
 */
export function usePublishLiveStatus(isLive) {
  const publish = useContext(LiveStatusContext)?.publish;

  useEffect(() => {
    if (!publish) return;
    publish(isLive);
    return () => publish(undefined);
  }, [publish, isLive]);
}
