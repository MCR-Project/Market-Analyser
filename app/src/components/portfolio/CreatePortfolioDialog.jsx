/**
 * CreatePortfolioDialog — where a new portfolio comes from.
 *
 * Three sources, because building a basket ticker by ticker is slow and
 * the interesting question is usually "what if I tweak SPY" rather than
 * "what if I start from nothing":
 *
 *   Blank      — an empty basket to fill in by hand
 *   An ETF     — a tracked fund's constituents, weights normalised
 *   A portfolio — a copy of one already saved
 *
 * A copied fund is deliberately not presented as the fund. Only
 * constituents weighing at least 1% of their fund are tracked (see the
 * data pipeline in the README), so copying SPY brings across the 46 names
 * that clear that bar and not the other ~450 — a bit over half its
 * weight. The dialog shows what share of the fund's published weights the
 * copy actually accounts for, and the resulting portfolio keeps saying so,
 * so nobody reads the result as "SPY" and wonders why it disagrees with
 * the real thing.
 */
import { useMemo, useState } from 'react';
import { useFetch } from '../../hooks/useFetch';
import { api } from '../../utils/api';
import { Loading } from '../ui/Loading';
import { ErrorState } from '../ui/ErrorState';
import { describeFetchError } from '../../utils/errorCopy';
import { Overlay } from '../ui/Overlay';
import { normaliseWeights } from '../../utils/weights';

/** Published fund weights that add up to about this much are the whole
 *  fund as far as anyone can tell — the remainder is rounding, not a gap
 *  worth warning about. */
const WHOLE_FUND_COVERAGE = 99;

const SOURCES = [
  { key: 'blank', label: 'Blank' },
  { key: 'etf', label: 'From an ETF' },
  { key: 'portfolio', label: 'From a portfolio' },
];

function Segmented({ value, onChange, disabled }) {
  return (
    <div role="tablist" aria-label="Start from" className="inline-flex p-1 bg-[var(--bg-3)] rounded-[var(--radius-md)] gap-0.5">
      {SOURCES.map(source => {
        const active = value === source.key;
        const off = disabled?.[source.key];
        return (
          <button
            key={source.key}
            role="tab"
            aria-selected={active}
            disabled={!!off}
            title={off}
            onClick={() => onChange(source.key)}
            className="px-3 py-1.5 border-none rounded-[7px] text-[12.5px] transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
            style={{
              cursor: off ? 'not-allowed' : 'pointer',
              fontWeight: active ? 700 : 500,
              background: active ? 'var(--bg-1)' : 'transparent',
              color: active ? 'var(--fg)' : 'var(--fg-2)',
              boxShadow: active ? 'var(--shadow-xs)' : 'none',
            }}
          >
            {source.label}
          </button>
        );
      })}
    </div>
  );
}

function PickList({ children }) {
  return (
    <div className="corr-scroll h-[228px] overflow-y-auto border border-[var(--border)] rounded-[var(--radius-md)] p-1.5">
      {children}
    </div>
  );
}

function PickRow({ active, onClick, title, subtitle }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left rounded-[var(--radius-sm)] border-none cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
      style={{ background: active ? 'var(--accent-soft)' : 'transparent' }}
    >
      <span className="min-w-0">
        <span
          className="block text-[13px] truncate"
          style={{ color: active ? 'var(--accent)' : 'var(--fg)', fontWeight: active ? 700 : 600 }}
        >
          {title}
        </span>
        <span className="block text-[11.5px] text-[var(--fg-2)] truncate">{subtitle}</span>
      </span>
    </button>
  );
}

/** What a copy of this fund actually is, said plainly. */
function CoverageNote({ holdings, coverage }) {
  const whole = coverage >= WHOLE_FUND_COVERAGE;
  return (
    <div className="mt-3 p-3 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-2)]">
      <div className="text-[12.5px] text-[var(--fg)] font-semibold">
        {holdings} tracked holdings · {coverage.toFixed(1)}% of the fund’s published weights
      </div>
      <p className="text-[12px] text-[var(--fg-2)] leading-relaxed m-0 mt-1">
        {whole
          ? 'That is the fund as tracked here, give or take the rounding in its published weights. They are rescaled to total 100% in the copy.'
          : 'Only constituents weighing at least 1% of a fund are tracked, so the rest of it is not in this copy. The weights that are here are rescaled to total 100%, which makes this a portfolio of the fund’s larger names rather than the fund itself.'}
      </p>
    </div>
  );
}

export function CreatePortfolioDialog({ portfolios, onCreate, onClose }) {
  const [source, setSource] = useState('blank');
  const [etfId, setEtfId] = useState(null);
  const [copyId, setCopyId] = useState(null);
  const [query, setQuery] = useState('');
  // Until the name is edited by hand it follows whatever is selected, so
  // picking SMH names it SMH without anyone having to type it.
  const [typedName, setTypedName] = useState(null);

  const { data: etfList, loading: etfsLoading, error: etfsError, retry: retryEtfs } = useFetch(
    (signal) => (source === 'etf' ? api.listEtfs({ signal }) : Promise.resolve(null)),
    [source],
    { fallback: null }
  );

  const { data: etfDetail, loading: detailLoading, error: detailError } = useFetch(
    (signal) => (etfId ? api.getEtf(etfId, { signal }) : Promise.resolve(null)),
    [etfId || ''],
    { fallback: null }
  );

  const etfs = useMemo(() => {
    const all = etfList || [];
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(e =>
      e.id.toLowerCase().includes(q) ||
      (e.name || '').toLowerCase().includes(q) ||
      (e.cat || '').toLowerCase().includes(q)
    );
  }, [etfList, query]);

  const copySource = portfolios.find(p => p.id === copyId) || null;

  // The fund's own holdings, and what share of it they represent. The
  // coverage is the sum *before* rescaling — the honest number, which for
  // a fund whose weights are refreshed piecemeal can land slightly over
  // 100 as well as under.
  const fundHoldings = useMemo(
    () => (etfDetail?.holdings || []).map(([ticker, weight]) => ({ ticker, weight })),
    [etfDetail]
  );
  const coverage = useMemo(
    () => fundHoldings.reduce((sum, h) => sum + h.weight, 0),
    [fundHoldings]
  );

  const suggestedName =
    source === 'etf' ? (etfId || '') :
    source === 'portfolio' ? (copySource ? `${copySource.name} (copy)` : '') :
    '';
  const name = typedName ?? suggestedName;

  const ready =
    source === 'blank' ||
    (source === 'etf' && fundHoldings.length > 0 && !detailLoading) ||
    (source === 'portfolio' && !!copySource);

  const submit = () => {
    if (!ready) return;
    if (source === 'etf') {
      onCreate({
        name: name.trim() || etfId,
        holdings: normaliseWeights(fundHoldings),
        source: { kind: 'etf', id: etfId, name: etfDetail?.name || etfId, coverage },
      });
    } else if (source === 'portfolio') {
      onCreate({
        name: name.trim() || `${copySource.name} (copy)`,
        // A deep copy: the two portfolios share no object from here on, so
        // editing one cannot reach into the other.
        holdings: copySource.holdings.map(h => ({ ...h })),
        value: copySource.value,
        rebalance: copySource.rebalance,
        // How it is funded is part of what the portfolio is, so a copy
        // that dropped the schedule would simulate differently from the
        // thing it says it is a copy of. Money in or money out (#150): a
        // portfolio has one or the other, and the copy keeps whichever.
        contribution: copySource.contribution && { ...copySource.contribution },
        withdrawal: copySource.withdrawal && { ...copySource.withdrawal },
        source: { kind: 'portfolio', id: copySource.id, name: copySource.name },
      });
    } else {
      onCreate({ name: name.trim() || undefined });
    }
  };

  return (
    <Overlay
      onClose={onClose}
      ariaLabel="New portfolio"
      className="fixed inset-0 z-80 flex items-start justify-center pt-[12vh] px-5 pb-5"
      style={{ background: 'color-mix(in oklab, var(--bg-inset) 70%, transparent)', backdropFilter: 'blur(3px)' }}
      contentClassName="w-full max-w-[560px] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] overflow-hidden animate-[corrPop_var(--dur-fast)_var(--ease-out)]"
    >
      <div className="flex items-start justify-between gap-4 p-5 pb-4 border-b border-[var(--divider)]">
        <div>
          <div className="eyebrow mb-2">NEW PORTFOLIO</div>
          <Segmented
            value={source}
            onChange={setSource}
            disabled={{ portfolio: portfolios.length === 0 ? 'No saved portfolios to copy yet' : undefined }}
          />
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="flex-none w-8 h-8 grid place-items-center bg-transparent border border-[var(--border)] rounded-[var(--radius-sm)] text-[var(--fg-2)] cursor-pointer hover:bg-[var(--bg-2)]"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
        </button>
      </div>

      <div className="p-5">
        {source === 'blank' && (
          <p className="text-[13.5px] text-[var(--fg-2)] leading-relaxed m-0 h-[228px]">
            An empty portfolio, to add tickers to one at a time.
          </p>
        )}

        {source === 'etf' && (
          <>
            <input
              value={query}
              onInput={e => setQuery(e.target.value)}
              placeholder="Search funds — SMH, semis, growth…"
              aria-label="Search funds"
              className="w-full h-[38px] px-3 mb-2.5 bg-[var(--bg-3)] border border-[var(--border)] rounded-[var(--radius-md)] text-[13px] text-[var(--fg)] outline-none focus:border-[var(--accent-ring)]"
            />
            {etfsError && !etfList ? (
              <ErrorState {...describeFetchError(etfsError)} onRetry={retryEtfs} />
            ) : (
              <PickList>
                {etfsLoading && !etfList ? (
                  <div className="p-2 flex flex-col gap-2.5">
                    {Array.from({ length: 5 }, (_, i) => <Loading key={i} variant="skeleton" lines={1} />)}
                  </div>
                ) : etfs.length === 0 ? (
                  <p className="text-[13px] text-[var(--fg-2)] m-0 p-3">No fund matches “{query}”.</p>
                ) : (
                  etfs.map(etf => (
                    <PickRow
                      key={etf.id}
                      active={etf.id === etfId}
                      onClick={() => setEtfId(etf.id)}
                      title={`${etf.id} · ${etf.name}`}
                      subtitle={`${etf.holdingCount} tracked holdings${etf.cat ? ` · ${etf.cat}` : ''}`}
                    />
                  ))
                )}
              </PickList>
            )}
            {etfId && (
              detailError ? (
                <p className="mt-3 text-[12.5px] text-[var(--warning)] m-0">
                  {etfId}’s holdings could not be loaded, so it cannot be copied right now.
                </p>
              ) : detailLoading || !etfDetail ? (
                <div className="mt-3"><Loading variant="skeleton" lines={2} /></div>
              ) : (
                <CoverageNote holdings={fundHoldings.length} coverage={coverage} />
              )
            )}
          </>
        )}

        {source === 'portfolio' && (
          <PickList>
            {portfolios.map(portfolio => (
              <PickRow
                key={portfolio.id}
                active={portfolio.id === copyId}
                onClick={() => setCopyId(portfolio.id)}
                title={portfolio.name}
                subtitle={`${portfolio.holdings.length} holdings · $${portfolio.value.toLocaleString('en-US')}`}
              />
            ))}
          </PickList>
        )}
      </div>

      <div className="flex items-end justify-between gap-4 p-5 pt-0">
        <label className="flex-1 min-w-0">
          <span className="eyebrow block mb-1.5">NAME</span>
          <input
            value={name}
            onInput={e => setTypedName(e.target.value)}
            placeholder="New portfolio"
            className="w-full h-[38px] px-3 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-md)] text-[13.5px] text-[var(--fg)] outline-none focus:border-[var(--accent-ring)]"
          />
        </label>
        <button
          onClick={submit}
          disabled={!ready}
          className="flex-none h-[38px] px-4 text-[13px] font-semibold text-[var(--accent)] bg-[var(--accent-soft)] border border-[var(--accent-ring)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--accent-ring)] disabled:opacity-45 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          Create
        </button>
      </div>
    </Overlay>
  );
}
