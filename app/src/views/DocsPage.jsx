/**
 * DocsPage — the measurement documentation page.
 *
 * Rendered inside AppLayout, which owns the shared Header; this is
 * everything below it.
 *
 *  ┌────────────────┬─────────────────────────────┐
 *  │ search         │                             │
 *  │ Official       │  MeasurementDoc:            │
 *  │  · Correlation │   prose, worked example,    │
 *  │  · % of ETF    │   reference panels          │
 *  │ Plugged-in     │                             │
 *  │  · …           │                             │
 *  └────────────────┴─────────────────────────────┘
 *
 * The sidebar comes from the backend manifest, so a measurement plugged
 * into addon_measurements/ appears here on its own. Which measurement is
 * open lives in the URL (/docs/:measurementId), so a doc is linkable.
 *
 * Whether a measurement exists is decided by the manifest, not by asking
 * for its doc and waiting for a 404 — that keeps an unknown id from
 * costing a pointless request, and lets the sidebar stay usable while the
 * content area explains that nothing matches.
 */
import { useState } from 'react';
import { useParams } from 'react-router';
import { useFetch } from '../hooks/useFetch';
import { api } from '../utils/api';
import { DocsSidebar } from '../components/docs/DocsSidebar';
import { MeasurementDoc } from '../components/docs/MeasurementDoc';
import { Loading } from '../components/ui/Loading';
import { ErrorState } from '../components/ui/ErrorState';
import { describeFetchError } from '../utils/errorCopy';

export function DocsPage() {
  const { measurementId } = useParams();
  const [query, setQuery] = useState('');

  const {
    data: manifestData,
    loading: manifestLoading,
    error: manifestError,
    retry: retryManifest,
  } = useFetch((signal) => api.listMeasurements({ signal }), [], { fallback: null });

  const manifest = manifestData || [];
  const entry = manifest.find(m => m.id === measurementId) || null;
  const unknownId = !!measurementId && !!manifestData && !entry;

  // Resolves to null (no request) until the manifest confirms the id is
  // real. `deps` stays a primitive, per useFetch's contract.
  const { data: doc, loading: docLoading, error: docError, retry: retryDoc } = useFetch(
    (signal) => (entry ? api.getMeasurementDoc(entry.id, { signal }) : Promise.resolve(null)),
    [entry?.id || ''],
    { fallback: null }
  );

  if (manifestError && !manifestData) {
    return (
      <main className="flex-1 min-h-0 overflow-auto px-6 py-8">
        <div className="max-w-[720px] mx-auto">
          <ErrorState {...describeFetchError(manifestError)} onRetry={retryManifest} />
        </div>
      </main>
    );
  }

  return (
    <div className="flex-1 min-h-0 flex">
      <aside className="corr-scroll flex-none w-[264px] overflow-y-auto border-r border-[var(--border)] p-4">
        {manifestLoading && !manifestData ? (
          <Loading variant="skeleton" lines={6} />
        ) : (
          <DocsSidebar manifest={manifest} query={query} onQueryChange={setQuery} />
        )}
      </aside>

      <main className="corr-scroll flex-1 min-w-0 overflow-y-auto px-8 py-8">
        <Content
          measurementId={measurementId}
          entry={entry}
          unknownId={unknownId}
          doc={doc}
          loading={docLoading || (!!measurementId && manifestLoading && !manifestData)}
          error={docError}
          onRetry={retryDoc}
        />
      </main>
    </div>
  );
}

function Content({ measurementId, entry, unknownId, doc, loading, error, onRetry }) {
  if (!measurementId) return <Landing />;
  if (unknownId) return <NotFound measurementId={measurementId} />;
  if (loading || (!doc && !error)) return <Loading variant="skeleton" lines={12} />;
  if (error) {
    return (
      <div className="max-w-[720px]">
        <ErrorState {...describeFetchError(error)} onRetry={onRetry} />
      </div>
    );
  }
  return <MeasurementDoc manifest={entry} doc={doc} />;
}

function Landing() {
  return (
    <div className="max-w-[600px]">
      <h1 className="text-[26px] font-extrabold text-[var(--fg)] tracking-tight mt-0 mb-3">
        Measurement documentation
      </h1>
      <p className="text-[14px] leading-relaxed text-[var(--fg-1)] m-0 mb-3">
        Every column in the holdings table is produced by a measurement — a
        self-contained plugin that fetches its own inputs, computes a value
        for each holding, and decides how that value is drawn.
      </p>
      <p className="text-[14px] leading-relaxed text-[var(--fg-2)] m-0">
        Pick one from the list to see what it measures, which data it starts
        from, how it is computed, and a worked example using real numbers
        from a real fund.
      </p>
    </div>
  );
}

function NotFound({ measurementId }) {
  return (
    <div className="max-w-[600px]">
      <h1 className="text-[22px] font-extrabold text-[var(--fg)] tracking-tight mt-0 mb-3">
        No measurement called “{measurementId}”
      </h1>
      <p className="text-[14px] leading-relaxed text-[var(--fg-2)] m-0">
        Nothing with that id is registered. It may have been renamed, or
        removed from the measurement registry — pick one from the list to
        carry on.
      </p>
    </div>
  );
}
