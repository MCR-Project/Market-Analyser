/**
 * SharedNotice — the banner above a portfolio that arrived in a link.
 *
 * Two things need saying, and neither is obvious from a page that looks
 * exactly like a saved portfolio:
 *
 *  - **It is not yours.** Nothing on this page writes to the library, and
 *    closing the tab loses it unless it is kept. The read-only panel below
 *    shows this by having nothing to click, which is easy to misread as a
 *    page that has not finished loading — so it is also said in words.
 *  - **It is a snapshot.** The portfolio is inside the link, not behind
 *    it: there is nothing on a server for the sender to update, so this
 *    stays as it was the moment they copied it, however much they change
 *    theirs afterwards.
 */
export function SharedNotice() {
  return (
    <div
      role="status"
      className="flex items-start gap-3 p-3.5 mb-6 rounded-[var(--radius-md)] border max-w-[860px]"
      style={{ background: 'var(--accent-soft)', borderColor: 'var(--accent-ring)' }}
    >
      <svg
        width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)"
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        className="flex-none mt-0.5" aria-hidden="true"
      >
        <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
        <path d="M16 6l-4-4-4 4" /><path d="M12 2v13" />
      </svg>
      <p className="text-[12.5px] text-[var(--fg-1)] leading-relaxed m-0">
        <strong className="font-bold">Shared with you.</strong> This portfolio
        travelled inside the link and is not saved in this browser — it is a
        snapshot of the moment it was shared, and will not follow any later
        changes its author makes. Everything here still simulates against
        live prices, and the window is yours to change.{' '}
        <strong className="font-bold">Save a copy</strong> to keep it and
        edit it as your own.
      </p>
    </div>
  );
}
