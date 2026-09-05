/**
 * DocsPage — placeholder for the measurement documentation page.
 *
 * The routes (/docs and /docs/:measurementId) are registered now so the
 * rest of the app can link to them; the real page — sidebar listing
 * official and plugged-in measurements, search, and the rendered doc
 * itself — is built separately.
 */
import { Link, useParams } from 'react-router';
import { useTheme } from '../hooks/useTheme';
import { DEFAULT_ETF_ID } from '../store/useEtfStore';

export function DocsPage() {
  const { measurementId } = useParams();

  // App applies the stored light/dark choice as a side effect of this
  // hook, so a route that doesn't mount App has to do it too — otherwise
  // opening /docs directly renders light for someone who chose dark.
  useTheme();

  return (
    <div className="h-screen overflow-auto flex flex-col items-center justify-center gap-3 px-6 bg-[var(--bg)] text-[var(--fg-1)] font-[var(--font-body)]">
      <div className="eyebrow">MEASUREMENT DOCUMENTATION</div>
      <p className="text-sm text-[var(--fg-2)] m-0 text-center">
        {measurementId
          ? <>Documentation for <span className="font-[var(--font-mono)] text-[var(--fg)]">{measurementId}</span> is not written yet.</>
          : 'Documentation for the measurement plugins is not written yet.'}
      </p>
      <Link to={`/etf/${DEFAULT_ETF_ID}`} className="font-[var(--font-mono)] text-xs font-semibold text-[var(--accent)] bg-[var(--accent-soft)] border border-[var(--accent-ring)] rounded-full px-4 py-1.5 no-underline">
        Back to the dashboard
      </Link>
    </div>
  );
}
