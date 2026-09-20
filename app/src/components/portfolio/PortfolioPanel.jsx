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
 *
 * **Layout** (issue #139). Below 2xl (1536px) everything stacks in one
 * 860px column: header, settings, window, results, holdings. At 2xl the
 * settings grid spreads into a single full-width row and the last two
 * sections sit side by side, so a weight can be edited with its effect
 * in view rather than a scroll away:
 *
 *  ┌ title · actions · provenance                        ┐
 *  │ settings (one row) · window · status · benchmarks   │
 *  ├──────────────────────┬──────────────────────────────┤
 *  │ holdings table       │ summary · risk               │
 *  │                      │ chart (fills the screen)     │
 *  └──────────────────────┴──────────────────────────────┘
 *
 * The settings grid is full width rather than heading the holdings
 * column (the layout first tried) so that the markup order, the stacked
 * order and the keyboard order stay one order: with settings in the
 * left column, focus went down to the settings, back up to the window
 * controls above them, then down again. Only the two columns are placed
 * out of markup order — results first in the markup, as in the stacked
 * layout, drawn on the right — so focus reads results then holdings.
 *
 * Results get the wider share (3 : 2): the chart is what benefits from
 * width, and the holdings table reads fine at around 600px. Comparison
 * mode takes the same results column.
 */
import { useCallback, useMemo, useState } from 'react';
import { useFetch } from '../../hooks/useFetch';
import { useComparisonRuns } from '../../hooks/useComparisonRuns';
import { usePortfolioSimulation } from '../../hooks/usePortfolioSimulation';
import { useSimulationWindow } from '../../hooks/useSimulationWindow';
import { useRiskFreeRate } from '../../hooks/useRiskFreeRate';
import { usePortfolioMetrics } from '../../hooks/usePortfolioMetrics';
import { usePortfolioRisk } from '../../hooks/usePortfolioRisk';
import {
  CONTRIBUTION_FREQUENCIES,
  DEFAULT_CONTRIBUTION,
  DEFAULT_WITHDRAWAL,
  REBALANCE_FREQUENCIES,
  WITHDRAWAL_FREQUENCIES,
  scheduleFields,
} from '../../store/portfolioStorage';
import { describeFetchError } from '../../utils/errorCopy';
import { api } from '../../utils/api';
import { AddHolding } from './AddHolding';
import { BenchmarkBar } from './BenchmarkBar';
import { ComparisonChart } from './ComparisonChart';
import { ComparisonSummary } from './ComparisonSummary';
import { PortfolioChart } from './PortfolioChart';
import { PortfolioRiskCard } from './PortfolioRiskCard';
import { PortfolioSummary } from './PortfolioSummary';
import { HoldingsTable } from './HoldingsTable';
import { WindowControls } from './WindowControls';
import { MetricsPicker } from '../ui/MetricsPicker';

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

const PERIOD_LABELS = {
  monthly: 'a month',
  quarterly: 'a quarter',
  yearly: 'a year',
};

/** Which way money moves. Three states of one choice rather than two
 *  schedules to fill in: a portfolio pays in or draws out, never both
 *  (ADR 0002), and a control that could pick both would need a message for
 *  the state it should never have allowed. */
const MONEY_FLOW_LABELS = {
  '': 'None',
  in: 'Pay in',
  out: 'Withdraw',
};

const ACTION_CLASS =
  'px-3 py-1.5 text-[12.5px] font-semibold rounded-[var(--radius-md)] border cursor-pointer transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2';

// The look of a field without its width, for the controls that share a row
// and so cannot each claim all of it: a `w-full` in the same class list
// would win over any narrower width added beside it.
const FIELD_BASE =
  'h-[30px] px-2 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-sm)] text-[13.5px] font-semibold text-[var(--fg)] outline-none focus:border-[var(--accent-ring)]';

const FIELD_CLASS = `w-full ${FIELD_BASE}`;

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

function Field({ label, wide = false, children }) {
  return (
    <div className={wide ? 'sm:col-span-2' : undefined}>
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

/**
 * Money paid in or drawn out on a schedule, or not at all (#67, #150).
 *
 * The direction is the switch, and it leads: "None" is the whole control
 * until there is a schedule to have a frequency and an amount for, so a
 * portfolio that takes a single lump sum shows one select rather than two
 * greyed-out boxes beside it. Turning it on fills in a placeholder amount
 * and monthly at once, because a schedule of nothing per month is not a
 * state worth being in on the way to a real one.
 *
 * One control rather than one each for paying in and drawing out, because
 * a portfolio does one or the other (ADR 0002): with two, "both" would be
 * a state to explain, and here it is one nobody can reach. Every change
 * writes both keys at once, the one it sets and the one it clears, so the
 * library is never left holding two.
 *
 * Switching direction keeps the amount and the frequency - somebody
 * comparing "$500 a month in" against "$500 a month out" is changing one
 * word, not retyping a schedule.
 *
 * The amount commits on blur like the opening amount does, and for the
 * same reason: halfway through typing 500 it reads 5, and re-simulating
 * a portfolio funded at $5 a month is work nobody asked for.
 */
function MoneyFlow({ portfolio, onChange }) {
  const [draft, setDraft] = useState(null);
  const direction = portfolio.contribution ? 'in' : portfolio.withdrawal ? 'out' : '';
  const schedule = portfolio.contribution || portfolio.withdrawal;
  const frequencies = direction === 'out' ? WITHDRAWAL_FREQUENCIES : CONTRIBUTION_FREQUENCIES;

  // `undefined` for the one that is not set, so the write clears it.
  const write = (next, to) => onChange(
    to === 'in'
      ? { contribution: next, withdrawal: undefined }
      : { contribution: undefined, withdrawal: next }
  );

  const commit = () => {
    if (draft !== null) {
      const parsed = Number(draft.replace(/[^0-9.]/g, ''));
      if (Number.isFinite(parsed) && parsed > 0) {
        write({ ...schedule, amount: parsed }, direction);
      }
    }
    setDraft(null);
  };

  const selectDirection = (to) => {
    setDraft(null);
    if (!to) {
      onChange({ contribution: undefined, withdrawal: undefined });
      return;
    }
    const allowed = to === 'in' ? CONTRIBUTION_FREQUENCIES : WITHDRAWAL_FREQUENCIES;
    write(
      {
        amount: schedule?.amount || (to === 'in' ? DEFAULT_CONTRIBUTION : DEFAULT_WITHDRAWAL),
        frequency: allowed.includes(schedule?.frequency) ? schedule.frequency : 'monthly',
      },
      to
    );
  };

  const selectFrequency = (frequency) => {
    setDraft(null);
    write({ ...schedule, frequency }, direction);
  };

  return (
    <div className="flex items-center gap-2">
      <select
        value={direction}
        aria-label="Money flow"
        onChange={e => selectDirection(e.target.value)}
        className={`${FIELD_BASE} cursor-pointer ${schedule ? 'w-[104px] flex-none' : 'w-full'}`}
      >
        {Object.entries(MONEY_FLOW_LABELS).map(([value, label]) => (
          <option key={value || 'none'} value={value}>{label}</option>
        ))}
      </select>
      {schedule && (
        <>
          <select
            value={schedule.frequency}
            aria-label="Money flow frequency"
            onChange={e => selectFrequency(e.target.value)}
            className={`${FIELD_BASE} cursor-pointer w-[112px] flex-none`}
          >
            {frequencies.map(frequency => (
              <option key={frequency} value={frequency}>{PERIOD_LABELS[frequency]}</option>
            ))}
          </select>
          <input
            value={draft ?? CURRENCY.format(schedule.amount)}
            aria-label="Money flow amount, USD"
            inputMode="decimal"
            onFocus={e => { setDraft(String(schedule.amount)); e.target.select(); }}
            onChange={e => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={e => {
              if (e.key === 'Enter') e.currentTarget.blur();
              if (e.key === 'Escape') { setDraft(null); e.currentTarget.blur(); }
            }}
            className={`${FIELD_BASE} min-w-0 flex-1`}
          />
        </>
      )}
    </div>
  );
}

/** How a portfolio's schedule reads when there is nothing to edit. */
function describeMoneyFlow(portfolio) {
  const amount = (schedule) => `${CURRENCY.format(schedule.amount)} ${PERIOD_LABELS[schedule.frequency]}`;
  if (portfolio.contribution) return `Pays in ${amount(portfolio.contribution)}`;
  if (portfolio.withdrawal) return `Withdraws ${amount(portfolio.withdrawal)}`;
  return 'Nothing';
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

/** A simulate payload for one line of the comparison. Each portfolio
 *  brings its own schedule, of either kind: comparing one that is paid into
 *  monthly with one that is drawn on, or with one that is neither, is a
 *  comparison somebody may well want, and flattening them to the same
 *  schedule would answer a question nobody asked. `schedule` is anything
 *  that holds the schedule - a portfolio, or the open one lent to a
 *  benchmark. */
function requestFor(holdings, value, rebalance, windowRequest, schedule) {
  return {
    holdings: holdings.filter(h => h.weight > 0).map(h => ({ ticker: h.ticker, weight: h.weight })),
    value,
    rebalance,
    ...scheduleFields(schedule),
    ...windowRequest,
  };
}

export function PortfolioPanel({
  portfolio,
  onRename,
  onUpdate,
  onShare,
  onExport,
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
  const { preset, request: windowRequest, start, end, selectPreset, setWindow } = useSimulationWindow();
  // No visible control reads this yet - see useRiskFreeRate.js's own
  // docstring for why - but merging it in here means a `?rf=` already
  // travels to the backend with every run and every comparison line,
  // ready for issue #112's tiles once they exist.
  const { request: rateRequest } = useRiskFreeRate();
  const request = useMemo(() => ({ ...windowRequest, ...rateRequest }), [windowRequest, rateRequest]);

  // The portfolio metric registry (issue #104) — which tiles PortfolioSummary
  // draws, and the dialog that toggles them. A view preference, not a write,
  // so it stays available on a read-only (shared) portfolio too.
  const portfolioMetrics = usePortfolioMetrics();
  const [metricsPickerOpen, setMetricsPickerOpen] = useState(false);

  // The same body `simulate` is asked with (issue #113's own "same body
  // shape" decision) - null rather than an empty request whenever there
  // is nothing to invest in, so usePortfolioRisk treats it the same way
  // usePortfolioSimulation treats no holdings: nothing to fetch, not an
  // error worth showing.
  const simulateRequest = useMemo(() => {
    if (!holdings.some(h => h.weight > 0)) return null;
    return requestFor(
      holdings, portfolio.value, portfolio.rebalance, request,
      { contribution: portfolio.contribution, withdrawal: portfolio.withdrawal }
    );
    // Only the fields the request is built from: depending on the whole
    // portfolio would rebuild it - and hand `usePortfolioRisk` a new object -
    // on a rename or any other edit that changes nothing it asks the backend.
  }, [holdings, portfolio.value, portfolio.rebalance, portfolio.contribution, portfolio.withdrawal, request]);
  const portfolioRisk = usePortfolioRisk(simulateRequest);
  const [riskPickerOpen, setRiskPickerOpen] = useState(false);

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
        request: requestFor(
          holdings, portfolio.value, portfolio.rebalance, request, portfolio
        ),
      },
      ...compared.map(other => ({
        key: other.id,
        label: other.name,
        kind: 'portfolio',
        request: requestFor(
          other.holdings || [], other.value, other.rebalance, request, other
        ),
      })),
      ...comparison.benchmarks.map(symbol => ({
        key: `benchmark:${symbol}`,
        label: symbol,
        kind: 'benchmark',
        // A benchmark takes the open portfolio's own funding, schedule
        // included and of either kind: "did this beat SPY" means against
        // the same money arriving - or leaving - on the same dates, not
        // against a lump sum.
        request: requestFor(
          [{ ticker: symbol, weight: 100 }], portfolio.value, 'none', request, portfolio
        ),
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
    <div className="max-w-[860px] 2xl:max-w-none">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-6">
        <Title portfolio={portfolio} onRename={onRename} readOnly={readOnly} />
        <div className="flex items-center gap-2 flex-none">
          <button
            onClick={() => setMetricsPickerOpen(true)}
            className={`${ACTION_CLASS} text-[var(--fg-1)] bg-[var(--bg-2)] border-[var(--border)] hover:bg-[var(--bg-3)] focus-visible:outline-[var(--accent)]`}
          >
            Metrics
          </button>
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
              {/* A file rather than a link (issue #148): this portfolio as
                  it is saved, to keep or to import somewhere else. Absent on
                  a shared one with the rest of the write side - it is not
                  yours to back up until it is kept. */}
              <button
                onClick={onExport}
                title="Save this portfolio to a file"
                className={`${ACTION_CLASS} text-[var(--fg-1)] bg-[var(--bg-2)] border-[var(--border)] hover:bg-[var(--bg-3)] focus-visible:outline-[var(--accent)]`}
              >
                Export
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

      {/* Two rows of four, with the money flow taking two columns because
          it is up to three controls. Read-only drops CREATED: a portfolio
          that came out of a link has no created date to show, since the
          copy is created when somebody keeps it. */}
      {/* At 2xl, six columns make it one row: amount, the two-column
          money flow, method, holdings, created. */}
      <div className="grid grid-cols-2 sm:grid-cols-4 2xl:grid-cols-6 gap-5 p-5 mb-6 bg-[var(--bg-1)] border border-[var(--border)] rounded-[var(--radius-lg)]">
        <Field label="AMOUNT">
          {readOnly ? (
            <Stated>{CURRENCY.format(portfolio.value)}</Stated>
          ) : (
            <Amount value={portfolio.value} onCommit={value => onUpdate({ value })} />
          )}
        </Field>
        {/* Reads left to right as a sentence: start with this much, pay
            in or withdraw this often, this much, run it this way. */}
        <Field label="MONEY FLOW" wide>
          {readOnly ? (
            <Stated>{describeMoneyFlow(portfolio)}</Stated>
          ) : (
            <MoneyFlow portfolio={portfolio} onChange={onUpdate} />
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

      {/* The two columns (2xl only). Results come first in the markup, as
          they do stacked, and are drawn on the right; both sit in row 1
          so neither is auto-placed below the other. */}
      <div className="2xl:grid 2xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] 2xl:gap-x-8 2xl:items-start">
        {/* One portfolio and nothing beside it is a question about its
            composition, which the stacked chart answers. The moment there is
            something to compare it with, the question becomes which grew
            faster - and a stack of one portfolio's holdings cannot answer
            that. */}
        <div className="2xl:col-start-2 2xl:row-start-1 min-w-0">
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
              <PortfolioSummary metrics={simulation.metrics} stale={stale || loading} portfolioMetrics={portfolioMetrics} />
              <PortfolioRiskCard portfolioRisk={portfolioRisk} onOpenPicker={() => setRiskPickerOpen(true)} />
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
        </div>

        <div className="2xl:col-start-1 2xl:row-start-1 min-w-0">
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
      </div>

      {metricsPickerOpen && (
        <MetricsPicker
          tileMetrics={portfolioMetrics.tileMetrics}
          families={portfolioMetrics.families}
          activeIds={portfolioMetrics.activeIds}
          onToggle={portfolioMetrics.toggle}
          onClose={() => setMetricsPickerOpen(false)}
        />
      )}

      {riskPickerOpen && (
        <MetricsPicker
          tileMetrics={portfolioRisk.tileMetrics}
          families={portfolioRisk.families}
          activeIds={portfolioRisk.activeIds}
          onToggle={portfolioRisk.toggle}
          onClose={() => setRiskPickerOpen(false)}
          eyebrow="PORTFOLIO RISK"
          subtitle="Select which tiles to show on the portfolio risk card"
          ariaLabel="Portfolio risk metrics"
          emptyText="No portfolio risk metrics available — is the backend running?"
        />
      )}
    </div>
  );
}
