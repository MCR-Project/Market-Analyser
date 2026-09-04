// Entry point — mounts the router into #root with StrictMode enabled.
//
// Routes:
//   /                        → redirect to the default ETF
//   /etf/:etfId              → dashboard, Table view
//   /etf/:etfId/:view        → dashboard, named view (table|matrix|network)
//   /docs                    → measurement documentation index
//   /docs/:measurementId     → one measurement's documentation
//
// The dashboard's ETF and view live in the URL rather than in memory, so
// a reload or a shared link reopens the same fund and the same view.
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router';
import './index.css';
import App from './App';
import { DocsPage } from './views/DocsPage';
import { DEFAULT_ETF_ID } from './store/useEtfStore';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to={`/etf/${DEFAULT_ETF_ID}`} replace />} />
        <Route path="/etf/:etfId" element={<App />} />
        <Route path="/etf/:etfId/:view" element={<App />} />
        <Route path="/docs" element={<DocsPage />} />
        <Route path="/docs/:measurementId" element={<DocsPage />} />
        {/* Anything unrecognised lands on the default ETF rather than a
            blank screen. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>
);
