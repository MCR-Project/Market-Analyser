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
 */
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { useComparison } from '../hooks/useComparison';
import { usePortfolios } from '../hooks/usePortfolios';
import { PortfolioSidebar } from '../components/portfolio/PortfolioSidebar';
import { PortfolioPanel } from '../components/portfolio/PortfolioPanel';
import { CreatePortfolioDialog } from '../components/portfolio/CreatePortfolioDialog';
import { DeletePortfolioDialog } from '../components/portfolio/DeletePortfolioDialog';
import { StorageNotice } from '../components/portfolio/StorageNotice';

export function PortfolioPage() {
  const { portfolioId } = useParams();
  const navigate = useNavigate();
  const { portfolios, status, create, update, rename, duplicate, remove } = usePortfolios();
  const [pendingDelete, setPendingDelete] = useState(null);
  const [creating, setCreating] = useState(false);

  const open = portfolios.find(p => p.id === portfolioId) || null;
  const unknownId = !!portfolioId && !open;
  const comparison = useComparison(portfolioId);

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

  return (
    <div className="flex-1 min-h-0 flex">
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

        {open ? (
          <PortfolioPanel
            portfolio={open}
            onRename={name => rename(open.id, name)}
            onUpdate={changes => update(open.id, changes)}
            compared={compared}
            comparison={comparison}
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
