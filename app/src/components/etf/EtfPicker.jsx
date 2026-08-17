/**
 * EtfPicker — full-screen dialog for switching the active ETF.
 *
 * Layout:
 *  ┌───────────────────────────────────────┐
 *  │ Search input (filters ETF list)       │
 *  ├──────────────┬────────────────────────┤
 *  │ ETF list     │ Preview panel:         │
 *  │ (scrollable, │  • ticker + name       │
 *  │  highlights  │  • description         │
 *  │  current &   │  • AUM, holding count  │
 *  │  hovered)    │  • top 5 holdings bars │
 *  │              │  • top sector          │
 *  └──────────────┴────────────────────────┘
 *
 * Fetches full ETF detail and sector breakdown for the hovered item from
 * the API (api.getEtf / api.getSectors). While either request is in
 * flight, the preview panel renders <Loading> placeholders instead of
 * stale or fabricated data.
 */
import { memo, useState, useMemo } from 'react';
import { fmtMoney } from '../../utils/format';
import { useFetch } from '../../hooks/useFetch';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { api } from '../../utils/api';
import { Loading } from '../ui/Loading';

export const EtfPicker = memo(function EtfPicker({ currentId, allEtfs, onSelect, onClose }) {
  const etfs = allEtfs || [];
  const [query, setQuery] = useState('');
  const [hovered, setHovered] = useState(currentId);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? etfs.filter(e => e.id.toLowerCase().includes(q) || e.name.toLowerCase().includes(q) || (e.cat || '').toLowerCase().includes(q)) : etfs;
  }, [query, etfs]);

  // Debounced so sweeping the mouse across the list doesn't fire a
  // preview + sectors request per hovered row — only the row the pointer
  // settles on for a beat triggers a fetch.
  const rawPreviewId = hovered || filtered[0]?.id || currentId;
  const previewId = useDebouncedValue(rawPreviewId, 150);

  const { data: preview, loading: previewLoading } = useFetch(
    (signal) => api.getEtf(previewId, { signal }),
    [previewId],
    { fallback: null }
  );

  const { data: sectorData, loading: sectorLoading } = useFetch(
    (signal) => api.getSectors(previewId, { signal }),
    [previewId],
    { fallback: null }
  );

  const holdings = preview?.holdings || [];
  const topSec = sectorData?.topSector || null;
  const maxHw = holdings[0]?.[1] || 1;

  const handleSelect = (id) => { onSelect(id); onClose(); };
  const handleKey = (e) => {
    if (e.key === 'Escape') onClose();
    if (e.key === 'Enter' && filtered.length) handleSelect(filtered[0].id);
  };

  return (
    <div onClick={onClose} className="fixed inset-0 z-80 flex items-start justify-center pt-[14vh] px-5 pb-5" style={{ background: 'color-mix(in oklab, var(--bg-inset) 70%, transparent)', backdropFilter: 'blur(3px)' }}>
      <div onClick={e => e.stopPropagation()} className="w-full max-w-[840px] bg-[var(--bg-1)] border border-[var(--border-strong)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] overflow-hidden animate-[corrPop_var(--dur-fast)_var(--ease-out)]">
        <div className="p-4 border-b border-[var(--divider)]">
          <div className="eyebrow mb-3">● SELECT AN ETF</div>
          <div className="flex items-center gap-2.5 h-[42px] px-3.5 bg-[var(--bg-3)] border border-[var(--border)] rounded-[var(--radius-md)]">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--fg-2)] flex-none"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
            <input value={query} onInput={e => setQuery(e.target.value)} onKeyDown={handleKey} autoFocus placeholder="Search — SPY, QQQ, MSCI World, semis…" className="flex-1 border-none outline-none bg-transparent text-[var(--fg)] font-[var(--font-body)] text-[15px]" />
          </div>
        </div>

        <div className="flex">
          <div className="corr-scroll w-[300px] flex-none overflow-y-auto p-2 border-r border-[var(--divider)]">
            {etfs.length === 0 && (
              <div className="p-3 flex flex-col gap-2.5">
                {Array.from({ length: 6 }, (_, i) => <Loading key={i} variant="skeleton" lines={1} />)}
              </div>
            )}
            {filtered.map(e => (
              <button key={e.id} onMouseEnter={() => setHovered(e.id)} onClick={() => handleSelect(e.id)}
                className="flex items-center justify-between gap-3 w-full p-3 border-none rounded-[10px] cursor-pointer text-left"
                style={{ background: e.id === currentId ? 'var(--accent-soft)' : (e.id === hovered ? 'var(--bg-2)' : 'transparent') }}
              >
                <span className="flex flex-col items-start gap-0.5 min-w-0">
                  <span className="font-semibold text-[var(--fg)] text-[15px]">{e.name}</span>
                  <span className="text-[13px] text-[var(--fg-2)]">{e.cat} · {e.holdingCount ?? 0} holdings</span>
                </span>
                <span className="font-[var(--font-mono)] text-sm font-bold text-[var(--accent)] flex-none">{e.id}</span>
              </button>
            ))}
            {etfs.length > 0 && filtered.length === 0 && <div className="p-4 text-sm text-[var(--fg-2)]">No ETF matches that. Try SPY, QQQ, SMH, or ARKK.</div>}
          </div>

          <div className="flex-1 p-6 flex flex-col gap-4 bg-[var(--bg)]" style={{ padding: '24px 26px' }}>
            {previewLoading || !preview ? (
              <>
                <Loading variant="skeleton" lines={3} />
                <Loading variant="skeleton" lines={2} className="pt-4 border-t border-[var(--divider)]" />
                <Loading variant="skeleton" lines={4} className="pt-4 border-t border-[var(--divider)]" />
              </>
            ) : (
              <>
                <div>
                  <div className="font-[var(--font-mono)] text-[30px] font-extrabold text-[var(--accent)] tracking-tight leading-none">{preview.id}</div>
                  <div className="text-base font-semibold text-[var(--fg)] mt-1.5 tracking-tight">{preview.name}</div>
                  <div className="text-xs text-[var(--fg-2)] mt-[3px] font-[var(--font-mono)]">{preview.cat}</div>
                </div>
                <p className="text-[13px] leading-relaxed text-[var(--fg-1)] m-0 pt-4 border-t border-[var(--divider)]">{preview.desc}</p>
                <div className="flex gap-6">
                  <div><div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-[3px]">NET ASSETS</div><div className="text-base font-bold text-[var(--fg)] tabular-nums">{fmtMoney(preview.aum)}</div></div>
                  <div><div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-[3px]">HOLDINGS</div><div className="text-base font-bold text-[var(--fg)] tabular-nums">{holdings.length}</div></div>
                </div>
                {holdings.length > 0 && (
                  <div>
                    <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-2.5">TOP HOLDINGS</div>
                    <div className="flex flex-col gap-2">
                      {holdings.slice(0, 5).map(([t, w]) => (
                        <div key={t} className="flex items-center gap-2.5">
                          <span className="w-12 flex-none font-[var(--font-mono)] text-xs font-bold text-[var(--accent)]">{t}</span>
                          <span className="flex-1 h-1.5 rounded-full bg-[var(--bg-3)] overflow-hidden"><span className="block h-full bg-[var(--accent)] rounded-full" style={{ width: Math.round((w / maxHw) * 100) + '%' }} /></span>
                          <span className="w-9 flex-none text-right font-[var(--font-mono)] text-[11px] text-[var(--fg-2)] tabular-nums">{w.toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div className="pt-4 border-t border-[var(--divider)]">
                  <div className="font-[var(--font-mono)] text-[10px] text-[var(--fg-2)] mb-2.5">TOP SECTOR</div>
                  {sectorLoading ? (
                    <Loading variant="skeleton" lines={1} />
                  ) : topSec ? (
                    <div className="flex items-center gap-3">
                      <span className="text-xl font-extrabold text-[var(--fg)] tracking-tight min-w-[72px]">{topSec.tag}</span>
                      <div className="flex-1 h-1.5 rounded-full bg-[var(--bg-3)] overflow-hidden"><div className="h-full bg-[var(--accent)] rounded-full" style={{ width: topSec.share + '%' }} /></div>
                      <span className="font-[var(--font-mono)] text-[13px] font-semibold text-[var(--accent)] tabular-nums">{topSec.share}%</span>
                    </div>
                  ) : (
                    <div className="text-[13px] text-[var(--fg-3)]">No sector data</div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
});
