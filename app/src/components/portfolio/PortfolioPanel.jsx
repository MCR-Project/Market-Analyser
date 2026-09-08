/**
 * PortfolioPanel — one portfolio: what it holds, and what that would have
 * been worth.
 *
 * The amount, the rebalancing method and the composition are all edited
 * here, and the numbers beside each holding come from the backend
 * simulation.
 *
 * The amount and the method apply as soon as they are chosen — each is a
 * single decision, made once. Weights are not: they are worked out by
 * comparison across the whole table, so they are edited freely and
 * applied together (see HoldingsTable), which is what keeps a table of
 * twenty holdings from re-simulating twenty times on the way to one
 * answer.
 *
 * A copied portfolio says where it came from, and — for a fund — what
 * share of it the copy actually accounted for. That note is history, not
 * a link: the copy is independent from the moment it exists, and the fund
 * moves on without it.
 *
 * Rename is inline on the title: the name is the thing being edited, so
 * editing it in place beats a dialog that shows the same word in a box.
 * Enter or blur commits, Escape restores what was there — an empty name
 * is refused by the library rather than leaving a row with nothing to
 * click.
 *
 * **Read-only** is the same panel with nothing to edit, used for a
 * portfolio that arrived in a link (#66) and is not in this browser's
 * library. It is the same component rather than a second one on purpose:
 * a shared portfolio has to simulate, chart and read exactly like a saved
 * one — that is the whole promise of the link — and two components
 * drawing the same portfolio would drift. Every control that would write
 * something is gone rather than disabled: a disabled row of buttons
 * invites a reader to work out why they cannot use them, when the answer
 * is that this portfolio is not theirs yet.
 */
import { useCallback, useMemo, useState } from 'react';
import { useFetch } from '../../hooks/useFetch';
import { useComparisonRuns } from '../../hooks/useComparisonRuns';
import { usePortfolioSimulation } from '../../hooks/usePortfolioSimulation';
import { useSimulationWindow } from '../../hooks/useSimulationWindow';
import { REBALANCE_FREQUENCIES } from '../../store/portfolioStorage';
import { describeFetchError } from '../../utils/errorCopy';
import { api } from '../../utils/api';
import { AddHolding } from './AddHolding';
import { BenchmarkBar } from './BenchmarkBar';
import { ComparisonChart } from './ComparisonChart';
import { ComparisonSummary } from './ComparisonSummary';
import { PortfolioChart } from './PortfolioChart';
import { PortfolioSummary } from './PortfolioSummary';
import { HoldingsTable } from './HoldingsTable';
import { WindowControls } from './WindowControls';

const CURRENCY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

const REBALANCE_LABELS = {
  none: 'Buy and hold',
  monthly: 'Rebalance monthly',
  quarterly: 'Rebalance quarterly',
  yearly: 'Rebalance yearly',
};

const ACTION_CLASS =
  'px-3 py-1.5 text-[12.5px] font-semibold rounded-[var(--radius-md)] border cursor-pointer transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2';

const FIELD_CLASS =
  'w-full h-[30px] px-2 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-sm)] text-[13.5px] font-semibold text-[var(--fg)] outline-none focus:border-[var(--accent-ring)]';

/** A fund copy is not the fund: only constituents weighing at least 1%
 *  are tracked, so a copy of SPY is its largest names and a bit over half
 *  its weight. Below this, the panel says so rather than leaving the
 *  number to speak for itself. */
const WHOLE_FUND_COVERAGE = 99;

function formatDate(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function Title({ portfolio, onRename, readOnly }) {
  const [draft, setDraft] = useState(null);

  // Switching portfolio mid-rename would otherwise carry the draft across
  // and rename the wrong one on blur. Adjusted during render rather than
  // in an effect, as App.jsx does with its selection — see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [editingId, setEditingId] = useState(portfolio.id);
  if (editingId !== portfolio.id) {
    setEditingId(portfolio.id);
    setDraft(null);
  }

  const commit = () => {
    if (draft !== null) onRename(draft);
    setDraft(null);
  };

  // After the hooks above, not before them: an early return that skips a
  // hook makes the next render a different component.
  if (readOnly) {
    return (
      <h1 className="text-[24px] font-extrabold text-[var(--fg)] tracking-tight m-0 truncate min-w-0">
        {portfolio.name}
      </h1>
    );
  }

  if (draft === null) {
    return (
      <div className="flex items-center gap-2.5 min-w-0">
        <h1 className="text-[24px] font-extrabold text-[var(--fg)] tracking-tight m-0 truncate">
          {portfolio.name}
        </h1>
        <button
          onClick={() => setDraft(portfolio.name)}
          aria-label={`Rename ${portfolio.name}`}
          className="flex-none w-8 h-8 grid place-items-center bg-transparent border border-[var(--border)] rounded-[var(--radius-sm)] text-[var(--fg-2)] cursor-pointer transition-colors duration-150 hover:bg-[var(--bg-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <input
      value={draft}
      autoFocus
      aria-label="Portfolio name"
      // Selecting on focus rather than in an effect: the name is almost
      // always being replaced, not appended to.
      onFocus={e => e.target.select()}
      onChange={e => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={e => {
        if (e.key === 'Enter') commit();
        if (e.key === 'Escape') setDraft(null);
      }}
      className="w-full max-w-[420px] px-3 h-[42px] text-[20px] font-extrabold tracking-tight text-[var(--fg)] bg-[var(--bg-1)] border border-[var(--accent-ring)] rounded-[var(--radius-md)] outline-none focus:border-[var(--accent)]"
    />
  );
}

/**
 * Where a copied portfolio came from — and, for a fund, the two ways it
 * is not that fund.
 *
 * **Coverage** is the small one: only constituents weighing at least 1%
 * are tracked, so a copy of a long-tailed fund is its larger names.
 *
 * **The as-of date is the large one.** The constituents are the fund's
 * *today*, and simulating them over the past assumes they were held all
 * along. They were not: a fund sells what disappointed it and buys what
 * did well, so backdating its current book buys the past with the
 * benefit of hindsight. The gap is not a rounding difference — a copy of
 * ARKK's holdings run from 2021 returns about +75% where the fund's own
 * shares returned about −30%. Somebody comparing the two and finding a
 * 100-point spread will reasonably suspect the simulator before they
 * suspect the survivorship, so the panel says it outright and points at
 * the one control that settles it.
 */
function Provenance({ source, windowStart }) {
  if (!source) return null;

  if (source.kind === 'portfolio') {
    return (
      <p className="text-[12.5px] text-[var(--fg-2)] leading-relaxed m-0 mb-5">
        Copied from “{source.name}”. The two have been independent ever since.
      </p>
    );
  }

  const coverage = Number.isFinite(source.coverage) ? source.coverage : null;
  return (
    <div className="mb-5">
      <p className="text-[12.5px] text-[var(--fg-2)] leading-relaxed m-0">
        Copied from{' '}
        <span className="font-[var(--font-mono)] text-[var(--fg-1)] font-bold">{source.id}</span>
        {source.name && source.name !== source.id ? ` · ${source.name}` : ''}
        {coverage === null
          ? '.'
          : coverage >= WHOLE_FUND_COVERAGE
            ? `, whose tracked holdings covered ${coverage.toFixed(1)}% of its published weights, rescaled to 100% here.`
            : `, whose tracked holdings covered ${coverage.toFixed(1)}% of its published weights — the rest of the fund sits in constituents too small to track, so this is a portfolio of its larger names rather than the fund itself.`}
      </p>
      <p
        className="flex items-start gap-2.5 text-[12.5px] leading-relaxed m-0 mt-2 p-3 rounded-[var(--radius-md)] border"
        style={{ background: 'var(--warning-soft)', borderColor: 'var(--warning-ring)', color: 'var(--fg-1)' }}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--warning)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-none mt-0.5" aria-hidden="true">
          <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" />
        </svg>
        <span>
          These are the fund's holdings <strong className="font-bold">as they are today</strong>,
          valued{windowStart ? <> back to <span className="font-[var(--font-mono)]">{windowStart}</span></> : ' over the whole window'}.
          The fund did not hold them then — it has sold what disappointed it
          and bought what did well since — so this run buys the past knowing
          how it turned out, and will usually beat the fund by a wide margin.
          Add{' '}
          <span className="font-[var(--font-mono)] text-[var(--fg)] font-bold">{source.id}</span>{' '}
          as a benchmark to see what the fund itself actually did.
        </span>
      </p>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <div className="eyebrow mb-1">{label}</div>
      {children}
    </div>
  );
}

/** A field's value with no box around it — the same height as the inputs
 *  beside it, so a read-only panel keeps the row on one line. */
function Stated({ children }) {
  return (
    <div className="text-[14px] text-[var(--fg)] font-semibold h-[30px] flex items-center truncate">
      {children}
    </div>
  );
}

/** The amount being simulated. Committed on blur rather than per
 *  keystroke: halfway through typing 10000 the value is 1, and a
 *  portfolio worth $1 is not what anybody meant. */
function Amount({ value, onCommit }) {
  const [draft, setDraft] = useState(null);

  const commit = () => {
    if (draft !== null) {
      const parsed = Number(draft.replace(/[^0-9.]/g, ''));
      if (Number.isFinite(parsed) && parsed > 0) onCommit(parsed);
    }
    setDraft(null);
  };

  return (
    <input
      value={draft ?? CURRENCY.format(value)}
      aria-label="Amount invested, USD"
      inputMode="decimal"
      onFocus={e => { setDraft(String(value)); e.target.select(); }}
      onChange={e => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={e => {
        if (e.key === 'Enter') e.currentTarget.blur();
        if (e.key === 'Escape') { setDraft(null); e.currentTarget.blur(); }
      }}
      className={FIELD_CLASS}
    />
  );
}

/** Which window the simulated columns describe, or why they are blank.
 *  The window is the backend's default for now; choosing one is #62. */
function SimulationStatus({ simulation, loading, error, onRetry, hasWeight }) {
  if (!hasWeight) return null;
  if (error) {
    return (
      <p role="status" className="text-[12px] text-[var(--warning)] leading-relaxed m-0 mb-2">
        {describeFetchError(error).message}{' '}
        <button
          onClick={onRetry}
          className="underline bg-transparent border-none p-0 text-[12px] text-[var(--warning)] cursor-pointer"
        >
          Try again
        </button>
      </p>
    );
  }
  if (!simulation) {
    return <p className="text-[12px] text-[var(--fg-2)] m-0 mb-2">{loading ? 'Simulating…' : ''}</p>;
  }
  return (
    <p className="text-[12px] text-[var(--fg-2)] m-0 mb-2">
      Value, return and contribution are simulated over{' '}
      <span className="font-[var(--font-mono)]">{simulation.start}</span> to{' '}
      <span className="font-[var(--font-mono)]">{simulation.end}</span>.
    </p>
  );
}

/** A simulate payload for one line of the comparison. */
function requestFor(holdings, value, rebalance, windowRequest) {
  return {
    holdings: holdings.filter(h => h.weight > 0).map(h => ({ ticker: h.ticker, weight: h.weight })),
    value,
    rebalance,
    ...windowRequest,
  };
}

export function PortfolioPanel({
  portfolio,
  onRename,
  onUpdate,
  onShare,
  onDuplicate,
  onDelete,
  compared = [],
  comparison,
  /** This portfolio came out of a link and is not in the library: show
   *  it, simulate it, and offer to keep it — but change nothing. */
  readOnly = false,
  onSaveCopy,
}) {
  // Memoised because it keys the comparison's request set: a fresh []
  // for a portfolio with no holdings would re-simulate every render.
  const holdings = useMemo(() => portfolio.holdings || [], [portfolio.holdings]);
  const [groupBy, setGroupBy] = useState('holding');
  const { preset, request, start, end, selectPreset, setWindow } = useSimulationWindow();

  // What the window was before a drag replaced it. A drag is easy to do
  // by accident and fiddly to undo by hand; choosing the window any other
  // way means the old one is no longer what anybody wants back.
  const [beforeDrag, setBeforeDrag] = useState(null);

  const selectByDrag = useCallback((dragged) => {
    setBeforeDrag(current => current ?? (preset ? { preset } : { start, end }));
    setWindow(dragged);
  }, [preset, start, end, setWindow]);

  const resetWindow = useCallback(() => {
    if (!beforeDrag) return;
    if (beforeDrag.preset) selectPreset(beforeDrag.preset);
    else setWindow(beforeDrag);
    setBeforeDrag(null);
  }, [beforeDrag, selectPreset, setWindow]);

  const chooseWindow = useCallback((chosen) => {
    setBeforeDrag(null);
    setWindow(chosen);
  }, [setWindow]);

  const choosePreset = useCallback((key) => {
    setBeforeDrag(null);
    selectPreset(key);
  }, [selectPreset]);
  const { simulation, loading, error, stale, retry } = usePortfolioSimulation(portfolio, request);

  // Sectors are only fetched once somebody asks to group by them: the
  // chart is about holdings until it isn't, and this is a request per
  // basket rather than per holding.
  const tickers = holdings.map(h => h.ticker).join(',');
  const { data: stocks } = useFetch(
    (signal) => (groupBy === 'sector' && tickers
      ? api.getStocks(tickers.split(','), { signal })
      : Promise.resolve(null)),
    [groupBy, tickers],
    { fallback: null }
  );
  const sectorOf = useMemo(
    () => new Map((stocks || []).map(stock => [stock.ticker, stock.sectorTag || 'UNKNOWN'])),
    [stocks]
  );

  // Every line on the comparison chart is a run of the same endpoint over
  // the same window: this portfolio, the others chosen from the list, and
  // each benchmark as a basket of one. A benchmark is given this
  // portfolio's own starting amount, so the dollar view compares two
  // answers to the same question rather than two different bets.
  const lines = useMemo(() => {
    if (!comparison?.comparing) return [];
    return [
      {
        key: portfolio.id,
        label: portfolio.name,
        kind: 'portfolio',
        request: requestFor(holdings, portfolio.value, portfolio.rebalance, request),
      },
      ...compared.map(other => ({
        key: other.id,
        label: other.name,
        kind: 'portfolio',
        request: requestFor(other.holdings || [], other.value, other.rebalance, request),
      })),
      ...comparison.benchmarks.map(symbol => ({
        key: `benchmark:${symbol}`,
        label: symbol,
        kind: 'benchmark',
        request: requestFor([{ ticker: symbol, weight: 100 }], portfolio.value, 'none', request),
      })),
    ];
  }, [comparison, portfolio, holdings, compared, request]);

  const comparisonRuns = useComparisonRuns(lines);

  const addHolding = (ticker) => {
    // The first holding takes the whole portfolio, because a basket where
    // every weight is zero cannot be simulated at all. Later ones start at
    // nothing rather than quietly rescaling weights somebody chose.
    const weight = holdings.some(h => h.weight > 0) ? 0 : 100;
    onUpdate({ holdings: [...holdings, { ticker, weight }] });
  };

  return (
    <div className="max-w-[860px]">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-6">
        <Title portfolio={portfolio} onRename={onRename} readOnly={readOnly} />
        <div className="flex items-center gap-2 flex-none">
          {readOnly ? (
            <button
              onClick={onSaveCopy}
              className={`${ACTION_CLASS} text-[var(--accent)] bg-[var(--accent-soft)] border-[var(--accent-ring)] hover:bg-[var(--accent-ring)] focus-visible:outline-[var(--accent)]`}
            >
              Save a copy
            </button>
          ) : (
            <>
              <button
                onClick={onShare}
                className={`${ACTION_CLASS} text-[var(--fg-1)] bg-[var(--bg-2)] border-[var(--border)] hover:bg-[var(--bg-3)] focus-visible:outline-[var(--accent)]`}
              >
                Share
              </button>
              <button
                onClick={onDuplicate}
                className={`${ACTION_CLASS} text-[var(--fg-1)] bg-[var(--bg-2)] border-[var(--border)] hover:bg-[var(--bg-3)] focus-visible:outline-[var(--accent)]`}
              >
                Duplicate
              </button>
              <button
                onClick={onDelete}
                className={`${ACTION_CLASS} text-[var(--danger)] bg-[var(--danger-soft)] border-[var(--danger-ring)] hover:bg-[var(--danger-ring)] focus-visible:outline-[var(--danger)]`}
              >
                Delete
              </button>
            </>
          )}
        </div>
      </div>

      <Provenance source={portfolio.source} windowStart={simulation?.start || null} />

      {/* Three columns read-only rather than four: when a portfolio came
          out of a link there is no created date to show - the copy is
          created when somebody keeps it. */}
      <div className={`grid grid-cols-2 gap-5 p-5 mb-6 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)] ${readOnly ? 'sm:grid-cols-3' : 'sm:grid-cols-4'}`}>
        <Field label="AMOUNT">
          {readOnly ? (
            <Stated>{CURRENCY.format(portfolio.value)}</Stated>
          ) : (
            <Amount value={portfolio.value} onCommit={value => onUpdate({ value })} />
          )}
        </Field>
        <Field label="METHOD">
          {readOnly ? (
            <Stated>{REBALANCE_LABELS[portfolio.rebalance]}</Stated>
          ) : (
            <select
              value={portfolio.rebalance}
              aria-label="Rebalancing method"
              onChange={e => onUpdate({ rebalance: e.target.value })}
              className={`${FIELD_CLASS} cursor-pointer`}
            >
              {REBALANCE_FREQUENCIES.map(frequency => (
                <option key={frequency} value={frequency}>{REBALANCE_LABELS[frequency]}</option>
              ))}
            </select>
          )}
        </Field>
        <Field label="HOLDINGS">
          <Stated>{holdings.length}</Stated>
        </Field>
        {!readOnly && (
          <Field label="CREATED">
            <Stated>{formatDate(portfolio.createdAt)}</Stated>
          </Field>
        )}
      </div>

      <WindowControls
        preset={preset}
        start={start}
        end={end}
        resolvedStart={simulation?.start || null}
        resolvedEnd={simulation?.end || null}
        onSelectPreset={choosePreset}
        onSetWindow={chooseWindow}
        canReset={!!beforeDrag}
        onReset={resetWindow}
      />

      <SimulationStatus
        simulation={simulation}
        loading={loading}
        error={error}
        onRetry={retry}
        hasWeight={holdings.some(h => h.weight > 0)}
      />

      {comparison && (
        <BenchmarkBar
          benchmarks={comparison.benchmarks}
          disabled={comparison.full}
          onAdd={comparison.addBenchmark}
          onRemove={comparison.removeBenchmark}
        />
      )}

      {/* One portfolio and nothing beside it is a question about its
          composition, which the stacked chart answers. The moment there is
          something to compare it with, the question becomes which grew
          faster - and a stack of one portfolio's holdings cannot answer
          that. */}
      {comparison?.comparing ? (
        comparisonRuns.runs ? (
          <>
            <ComparisonChart
              runs={comparisonRuns.runs}
              stale={comparisonRuns.stale}
              onSelectWindow={selectByDrag}
            />
            <ComparisonSummary runs={comparisonRuns.runs} stale={comparisonRuns.stale} />
          </>
        ) : (
          <p className="text-[12px] text-[var(--fg-2)] m-0 mb-4">Simulating each line…</p>
        )
      ) : simulation && (
        <>
          <PortfolioSummary metrics={simulation.metrics} stale={stale || loading} />
          <PortfolioChart
            simulation={simulation}
            groupBy={groupBy}
            onGroupByChange={setGroupBy}
            sectorOf={sectorOf}
            sectorsReady={!!stocks}
            stale={stale || loading}
            onSelectWindow={selectByDrag}
          />
        </>
      )}

      <HoldingsTable
        portfolioId={portfolio.id}
        holdings={holdings}
        simulation={simulation}
        stale={stale || loading}
        readOnly={readOnly}
        onChange={next => onUpdate({ holdings: next })}
        addControl={
          readOnly ? null : (
            <AddHolding
              existing={holdings}
              windowStart={simulation?.start || null}
              onAdd={addHolding}
            />
          )
        }
      />
    </div>
  );
}
