// Entry point — mounts the router into #root with StrictMode enabled.
//
// Routes:
//   /                        → redirect to the default ETF
//   /etf/:etfId              → dashboard, Table view
//   /etf/:etfId/:view        → dashboard, named view (table|matrix|network)
//   /docs                    → measurement documentation index
//   /docs/:measurementId     → one measurement's documentation
//   /portfolio               → the portfolio library
//   /portfolio/shared?p=…    → a portfolio carried by the link itself
//   /portfolio/:portfolioId  → one saved portfolio
//
// The dashboard's ETF and view live in the URL rather than in memory, so
// a reload or a shared link reopens the same fund and the same view.
import { StrictMode, Suspense, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router';
import './index.css';
import App from './App';
import { AppLayout } from './components/layout/AppLayout';
import { PortfolioPage } from './views/PortfolioPage';
import { DEFAULT_ETF_ID } from './store/useEtfStore';

// Split out so the dashboard doesn't carry the docs page's weight —
// KaTeX and its fonts are a third of the bundle and are only ever needed
// once someone opens a measurement's documentation.
// This is the entry module: it has no exports by design, so there is no
// fast-refresh boundary for the rule below to protect.
// eslint-disable-next-line react-refresh/only-export-components
const DocsPage = lazy(() =>
  import('./views/DocsPage').then(m => ({ default: m.DocsPage }))
);

/** Neutral placeholder while the docs chunk loads, under the header. */
const docsFallback = <div className="flex-1 bg-[var(--bg)]" />;

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        {/* One layout wraps every page, so the header is a single element
            shared across them rather than one rebuilt per page. */}
        <Route element={<AppLayout />}>
          <Route path="/" element={<Navigate to={`/etf/${DEFAULT_ETF_ID}`} replace />} />
          <Route path="/etf/:etfId" element={<App />} />
          <Route path="/etf/:etfId/:view" element={<App />} />
          <Route path="/docs" element={<Suspense fallback={docsFallback}><DocsPage /></Suspense>} />
          <Route path="/docs/:measurementId" element={<Suspense fallback={docsFallback}><DocsPage /></Suspense>} />
          {/* Not split out like the docs page: the library has no heavy
              dependencies of its own, so a separate chunk would cost a
              round-trip to save nothing. */}
          <Route path="/portfolio" element={<PortfolioPage />} />
          {/* Before the id route for readability; react-router ranks a
              static segment above a dynamic one either way, and portfolio
              ids are UUIDs, so "shared" is not one anybody can collide
              with. */}
          <Route path="/portfolio/shared" element={<PortfolioPage shared />} />
          <Route path="/portfolio/:portfolioId" element={<PortfolioPage />} />
          {/* Anything unrecognised lands on the default ETF rather than a
              blank screen. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>
);
