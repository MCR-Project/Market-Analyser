/**
 * PortfolioPage — the portfolio library.
 *
 * Rendered inside AppLayout, which owns the shared Header; this is
 * everything below it.
 *
 *  ┌────────────────┬─────────────────────────────┐
 *  │ + New portfolio│                             │
 *  │ Semis, equal…  │  PortfolioPanel:            │
 *  │ Copy of SPY    │   name, amount, method,     │
 *  │ …              │   composition, actions      │
 *  └────────────────┴─────────────────────────────┘
 *
 * Which portfolio is open lives in the URL (/portfolio/:portfolioId), the
 * same way the dashboard's fund does, so a reload reopens it. The
 * portfolios themselves live in this browser's storage — there are no
 * accounts here, and these are simulations rather than holdings anyone
 * owns — so an id from another machine is simply unknown, which the
 * content area explains while the sidebar stays usable.
 *
 * `/portfolio/shared` is the exception, and the one route where the
 * portfolio is not in this browser at all: it comes out of the query
 * string (#66, portfolioLink.js). The page is otherwise the same page —
 * same sidebar, same panel, same simulation — because a shared portfolio
 * that behaved differently from a saved one would be a worse answer to
 * "what did they build". It is read-only until somebody keeps it, and
 * nothing about it touches storage before then.
 */
import { useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router';
import { useComparison } from '../hooks/useComparison';
import { usePortfolios } from '../hooks/usePortfolios';
import { SHARE_PARAM, decodePortfolio, encodePortfolio } from '../store/portfolioLink';
import { PRESETS } from '../hooks/useSimulationWindow';
import { PortfolioSidebar } from '../components/portfolio/PortfolioSidebar';
import { PortfolioPanel } from '../components/portfolio/PortfolioPanel';
import { CreatePortfolioDialog } from '../components/portfolio/CreatePortfolioDialog';
import { DeletePortfolioDialog } from '../components/portfolio/DeletePortfolioDialog';
import { SharePortfolioDialog } from '../components/portfolio/SharePortfolioDialog';
import { SharedNotice } from '../components/portfolio/SharedNotice';
import { StorageNotice } from '../components/portfolio/StorageNotice';

/** The view parameters worth carrying into a shared link: what the sender
 *  was looking at, so the recipient opens the same reading rather than the
 *  default one. `compare` is deliberately absent — it names portfolio ids,
 *  which mean nothing in another browser. `rf` (issue #103) travels for
 *  the same reason `window`/`start`/`end` do: a Sharpe someone sends
 *  should be the Sharpe they saw, rate included. `metrics` (issue #104)
 *  travels for the same reason again — which tiles the sender chose to
 *  show is part of what they are sharing. */
const SHARED_VIEW_PARAMS = ['window', 'start', 'end', 'benchmark', 'rf', 'metrics'];

/** How to describe the window a share link carries, for the dialog that
 *  is about to hand it over. */
function describeWindow(params) {
  const preset = PRESETS.find(option => option.key === params.get('window'));
  if (preset) return preset.label;
  const start = params.get('start');
  const end = params.get('end');
  if (start && end) return `${start} to ${end}`;
  return null;
}

export function PortfolioPage({ shared = false }) {
  const { portfolioId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { portfolios, status, create, update, rename, duplicate, remove } = usePortfolios();
  const [pendingDelete, setPendingDelete] = useState(null);
  const [creating, setCreating] = useState(false);
  const [sharing, setSharing] = useState(false);

  // Decoded from the URL rather than held in state: the link is the
  // source of truth, the same way the window and the comparison are, and
  // a reload has to produce the same portfolio.
  const payload = shared ? searchParams.get(SHARE_PARAM) : null;
  const link = useMemo(() => (shared ? decodePortfolio(payload) : null), [shared, payload]);

  const saved = portfolios.find(p => p.id === portfolioId) || null;
  // A shared portfolio needs an id for the panel to key its editing
  // session off, and this one is never stored: the copy gets a real id of
  // its own the moment somebody keeps it.
  const open = shared ? (link.portfolio && { ...link.portfolio, id: 'shared' }) : saved;
  const unknownId = !shared && !!portfolioId && !saved;
  const comparison = useComparison(shared ? null : portfolioId);

  // Ids in the URL are only meaningful in the browser that wrote them, so
  // a link comparing somebody else's portfolios shows what it can find
  // rather than an error about what it cannot.
  const compared = comparison.compareIds
    .map(id => portfolios.find(p => p.id === id))
    .filter(Boolean);

  // Creating opens what was created: the point of the button is to start
  // working on the new portfolio, not to admire it in the list.
  const handleCreate = (seed) => {
    setCreating(false);
    navigate(`/portfolio/${create(seed).id}`);
  };

  const handleDuplicate = () => {
    const copy = duplicate(open.id);
    if (copy) navigate(`/portfolio/${copy.id}`);
  };

  const handleDelete = () => {
    remove(pendingDelete.id);
    setPendingDelete(null);
    // Back to the library rather than to a URL naming something that no
    // longer exists, which would land on the not-found state.
    if (pendingDelete.id === portfolioId) navigate('/portfolio');
  };

  // The link for the open portfolio, built only while the dialog is up:
  // encoding every render would be work nobody asked for on a page that
  // re-renders on every keystroke in the holdings table.
  const shareUrl = useMemo(() => {
    if (!sharing || !saved) return '';
    const params = new URLSearchParams({ [SHARE_PARAM]: encodePortfolio(saved) });
    for (const key of SHARED_VIEW_PARAMS) {
      const value = searchParams.get(key);
      if (value) params.set(key, value);
    }
    return `${globalThis.location.origin}/portfolio/shared?${params}`;
  }, [sharing, saved, searchParams]);

  // Keeping a shared portfolio makes it an ordinary new one - a fresh id,
  // its own timestamps, and no tie to the link it arrived in. The view
  // parameters come along so the copy opens on the reading that was on
  // screen a moment ago, rather than jumping to the default window.
  const handleSaveCopy = () => {
    const kept = create(link.portfolio);
    const params = new URLSearchParams();
    for (const key of SHARED_VIEW_PARAMS) {
      const value = searchParams.get(key);
      if (value) params.set(key, value);
    }
    const query = params.toString();
    navigate(`/portfolio/${kept.id}${query ? `?${query}` : ''}`);
  };

  // Capped and centred past 2400px (issue #139): up to there the panel
  // spreads into its two columns, beyond it a table stretched across an
  // ultrawide monitor reads worse than a page with margins.
  return (
    <div className="flex-1 min-h-0 flex w-full max-w-[2400px] mx-auto">
      <aside className="flex-none w-[264px] border-r border-[var(--border)] p-4 min-h-0">
        <PortfolioSidebar
          portfolios={portfolios}
          onCreate={() => setCreating(true)}
          openId={portfolioId}
          comparedIds={comparison.compareIds}
          onToggleCompare={open ? comparison.toggleCompare : undefined}
          comparisonFull={comparison.full}
        />
      </aside>

      <main className="corr-scroll flex-1 min-w-0 overflow-y-auto px-8 py-8">
        <div className="max-w-[720px]">
          <StorageNotice status={status} />
        </div>

        {shared && !link.error && <SharedNotice />}

        {shared && link.error ? (
          <BadLink message={link.error} />
        ) : open ? (
          <PortfolioPanel
            portfolio={open}
            readOnly={shared}
            onSaveCopy={handleSaveCopy}
            onRename={name => rename(open.id, name)}
            onUpdate={changes => update(open.id, changes)}
            compared={compared}
            comparison={comparison}
            onShare={() => setSharing(true)}
            onDuplicate={handleDuplicate}
            onDelete={() => setPendingDelete(open)}
          />
        ) : unknownId ? (
          <NotFound portfolioId={portfolioId} />
        ) : (
          <Landing hasPortfolios={portfolios.length > 0} onCreate={() => setCreating(true)} />
        )}
      </main>

      {creating && (
        <CreatePortfolioDialog
          portfolios={portfolios}
          onCreate={handleCreate}
          onClose={() => setCreating(false)}
        />
      )}

      {sharing && saved && (
        <SharePortfolioDialog
          portfolio={saved}
          url={shareUrl}
          windowLabel={describeWindow(searchParams)}
          onClose={() => setSharing(false)}
        />
      )}

      {pendingDelete && (
        <DeletePortfolioDialog
          portfolio={pendingDelete}
          onConfirm={handleDelete}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}

function Landing({ hasPortfolios, onCreate }) {
  return (
    <div className="max-w-[600px]">
      <h1 className="text-[26px] font-extrabold text-[var(--fg)] tracking-tight mt-0 mb-3">
        Portfolios
      </h1>
      <p className="text-[14px] leading-relaxed text-[var(--fg-1)] m-0 mb-3">
        A portfolio here is a simulation: a basket of tickers and the share
        of the money each one takes, valued across whatever stretch of
        history you point it at. Nothing is bought, and nothing is
        connected to a broker.
      </p>
      <p className="text-[14px] leading-relaxed text-[var(--fg-2)] m-0 mb-5">
        {hasPortfolios
          ? 'Pick one from the list to see it, or start another.'
          : 'They are saved in this browser and nowhere else — there is no account to sign in to, and no copy on a server.'}
      </p>
      {!hasPortfolios && (
        <button
          onClick={onCreate}
          className="px-4 py-2 text-sm font-semibold text-[var(--accent)] bg-[var(--accent-soft)] border border-[var(--accent-ring)] rounded-[var(--radius-md)] cursor-pointer transition-colors duration-150 hover:bg-[var(--accent-ring)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          Create your first portfolio
        </button>
      )}
    </div>
  );
}

/** A link that did not survive the trip. Nothing is drawn beside it: a
 *  payload that failed validation is not a portfolio that can be shown
 *  partially, and half of somebody else's portfolio is worse than none. */
function BadLink({ message }) {
  return (
    <div className="max-w-[600px]">
      <h1 className="text-[22px] font-extrabold text-[var(--fg)] tracking-tight mt-0 mb-3">
        This shared portfolio could not be opened
      </h1>
      <p className="text-[14px] leading-relaxed text-[var(--fg-1)] m-0 mb-3">{message}</p>
      <p className="text-[13px] leading-relaxed text-[var(--fg-2)] m-0">
        Shared portfolios travel inside the link itself, so a link that was
        shortened, wrapped across two lines, or cut off at the end of a
        message no longer contains one. Nothing has been saved or changed
        in this browser.
      </p>
    </div>
  );
}

function NotFound({ portfolioId }) {
  return (
    <div className="max-w-[600px]">
      <h1 className="text-[22px] font-extrabold text-[var(--fg)] tracking-tight mt-0 mb-3">
        No portfolio with that id
      </h1>
      <p className="text-[14px] leading-relaxed text-[var(--fg-2)] m-0">
        Nothing in this browser is saved under{' '}
        <code className="font-[var(--font-mono)] text-[13px] text-[var(--fg-1)]">{portfolioId}</code>.
        It may have been deleted, or created in another browser — portfolios
        are stored on the machine that made them. Pick one from the list, or
        start a new one.
      </p>
    </div>
  );
}
