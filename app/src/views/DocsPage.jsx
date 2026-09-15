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
import { useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { useFetch } from '../hooks/useFetch';
import { api } from '../utils/api';
import { DocsSidebar } from '../components/docs/DocsSidebar';
import { MeasurementDoc } from '../components/docs/MeasurementDoc';
import { PortfolioMetricDoc } from '../components/docs/PortfolioMetricDoc';
import { Loading } from '../components/ui/Loading';
import { ErrorState } from '../components/ui/ErrorState';
import { describeFetchError } from '../utils/errorCopy';

export function DocsPage() {
  const { measurementId } = useParams();
  const [query, setQuery] = useState('');

  const {
    data: measurementData,
    loading: measurementsLoading,
    error: measurementsError,
    retry: retryMeasurements,
  } = useFetch((signal) => api.listMeasurements({ signal }), [], { fallback: null });

  // Portfolio metrics (issue #104) join the same /docs route as their own
  // sidebar group — a separate manifest fetch, merged below, so a
  // measurement's id space and a metric's stay two independent registries
  // that happen to share one page rather than one growing to know about
  // the other.
  const {
    data: metricData,
    loading: metricsLoading,
    error: metricsError,
    retry: retryMetrics,
  } = useFetch((signal) => api.listPortfolioMetrics({ signal }), [], { fallback: null });

  const manifestLoading = measurementsLoading || metricsLoading;
  const manifestData = measurementData && metricData ? true : null;

  const manifest = useMemo(() => [
    ...(measurementData || []),
    ...(metricData?.metrics || []),
  ], [measurementData, metricData]);
  const families = metricData?.families || {};

  const entry = manifest.find(m => m.id === measurementId) || null;
  const isMetric = entry?.origin === 'portfolio';
  const unknownId = !!measurementId && !!manifestData && !entry;

  // Resolves to null (no request) until both manifests have confirmed the
  // id is real, and which registry it belongs to. `deps` stays a
  // primitive, per useFetch's contract.
  const { data: doc, loading: docLoading, error: docError, retry: retryDoc } = useFetch(
    (signal) => {
      if (!entry) return Promise.resolve(null);
      return isMetric
        ? api.getPortfolioMetricDoc(entry.id, { signal })
        : api.getMeasurementDoc(entry.id, { signal });
    },
    [entry?.id || ''],
    { fallback: null }
  );

  const retryManifest = () => { retryMeasurements(); retryMetrics(); };

  if ((measurementsError || metricsError) && !manifestData) {
    return (
      <main className="flex-1 min-h-0 overflow-auto px-6 py-8">
        <div className="max-w-[720px] mx-auto">
          <ErrorState {...describeFetchError(measurementsError || metricsError)} onRetry={retryManifest} />
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
          isMetric={isMetric}
          families={families}
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

function Content({ measurementId, entry, isMetric, families, unknownId, doc, loading, error, onRetry }) {
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
  return isMetric
    ? <PortfolioMetricDoc manifest={entry} doc={doc} families={families} />
    : <MeasurementDoc manifest={entry} doc={doc} />;
}

function Landing() {
  return (
    <div className="max-w-[600px]">
      <h1 className="text-[26px] font-extrabold text-[var(--fg)] tracking-tight mt-0 mb-3">
        Documentation
      </h1>
      <p className="text-[14px] leading-relaxed text-[var(--fg-1)] m-0 mb-3">
        Every column in the holdings table is produced by a measurement — a
        self-contained plugin that fetches its own inputs, computes a value
        for each holding, and decides how that value is drawn. Every tile in
        a portfolio's summary comes from a portfolio metric the same way
        (issue #104).
      </p>
      <p className="text-[14px] leading-relaxed text-[var(--fg-2)] m-0">
        Pick one from the list to see what it measures, which data it starts
        from, how it is computed, and a worked example using real numbers
        from a real fund or a real simulated run.
      </p>
    </div>
  );
}

function NotFound({ measurementId }) {
  return (
    <div className="max-w-[600px]">
      <h1 className="text-[22px] font-extrabold text-[var(--fg)] tracking-tight mt-0 mb-3">
        Nothing called “{measurementId}”
      </h1>
      <p className="text-[14px] leading-relaxed text-[var(--fg-2)] m-0">
        Nothing with that id is registered as a measurement or a portfolio
        metric. It may have been renamed, or removed from its registry —
        pick one from the list to carry on.
      </p>
    </div>
  );
}
