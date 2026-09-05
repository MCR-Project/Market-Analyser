/**
 * DocsPage — measurement documentation.
 *
 * Currently the minimum needed to reach a rendered doc: it resolves
 * /docs/:measurementId, fetches that measurement's manifest entry and
 * its .mdx, and hands both to MeasurementDoc. The sidebar listing
 * official and plugged-in measurements, the search box, and the
 * not-found/empty states are built separately.
 */
import { Link, useParams } from 'react-router';
import { useFetch } from '../hooks/useFetch';
import { useTheme } from '../hooks/useTheme';
import { api } from '../utils/api';
import { MeasurementDoc } from '../components/docs/MeasurementDoc';
import { Loading } from '../components/ui/Loading';
import { ErrorState } from '../components/ui/ErrorState';
import { describeFetchError } from '../utils/errorCopy';
import { DEFAULT_ETF_ID } from '../store/useEtfStore';

export function DocsPage() {
  const { measurementId } = useParams();

  // App applies the stored light/dark choice as a side effect of this
  // hook, so a route that doesn't mount App has to do it too — otherwise
  // opening /docs directly renders light for someone who chose dark.
  useTheme();

  const { data: manifest } = useFetch(
    (signal) => api.listMeasurements({ signal }),
    [],
    { fallback: null }
  );

  const { data: doc, loading, error, retry } = useFetch(
    (signal) => (measurementId ? api.getMeasurementDoc(measurementId, { signal }) : Promise.resolve(null)),
    [measurementId || ''],
    { fallback: null }
  );

  const entry = (manifest || []).find(m => m.id === measurementId) || null;

  return (
    <div className="h-screen overflow-auto bg-[var(--bg)] text-[var(--fg-1)] font-[var(--font-body)]">
      <div className="max-w-[1280px] mx-auto px-6 py-8">
        <Link to={`/etf/${DEFAULT_ETF_ID}`} className="inline-block font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] no-underline mb-6 hover:text-[var(--fg)]">
          ← Back to the dashboard
        </Link>

        {!measurementId ? (
          <p className="text-sm text-[var(--fg-2)]">
            Pick a measurement to read about it.
          </p>
        ) : loading ? (
          <Loading variant="skeleton" lines={10} />
        ) : error || !doc ? (
          <ErrorState {...describeFetchError(error)} onRetry={retry} />
        ) : (
          <MeasurementDoc manifest={entry} doc={doc} />
        )}
      </div>
    </div>
  );
}
