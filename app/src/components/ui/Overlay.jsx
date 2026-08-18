/**
 * Overlay — shared full-screen dialog wrapper for StockPopup, EtfPicker and
 * MeasurementPicker.
 *
 * Provides the backdrop + stopPropagation panel structure the three popups
 * used to duplicate, plus the keyboard/accessibility behaviour none of them
 * had on their own:
 *  - role="dialog" / aria-modal="true" / an accessible name (aria-label or
 *    aria-labelledby)
 *  - Escape closes the dialog no matter which descendant has focus, not
 *    just when an inner input is focused
 *  - Tab / Shift+Tab is trapped to the focusable elements inside the dialog
 *  - focus moves into the dialog on open and back to the element that
 *    triggered it once the dialog unmounts
 */
import { useEffect, useRef } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function getFocusable(node) {
  return Array.from(node.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
    (el) => el.getClientRects().length > 0
  );
}

export function Overlay({
  onClose,
  ariaLabel,
  labelledBy,
  className,
  style,
  contentClassName,
  contentStyle,
  children,
}) {
  const contentRef = useRef(null);
  // Kept in a ref so the mount-only effect below always calls the latest
  // onClose without needing it in its dependency array (the parents pass a
  // fresh closure every render, which would otherwise re-run the effect —
  // and re-steal/restore focus — on every unrelated re-render).
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    const node = contentRef.current;
    const triggerEl = document.activeElement;

    const initial = getFocusable(node)[0] || node;
    initial.focus();

    // Registered on `document`, not `node`: a keydown listener scoped to the
    // dialog only ever sees events whose target is a descendant of it. That
    // breaks the moment focus ends up outside the dialog while it's still
    // open — e.g. in StockPopup, clicking a peer card focuses that button
    // and then navigates to it, which can remove the very button just
    // clicked from the new peer list. The browser then drops focus to
    // document.body, which is outside `node`'s subtree, so a node-scoped
    // listener would stop seeing Escape/Tab entirely. A document-level
    // listener keeps working regardless of where focus currently is.
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key === 'Tab') {
        const els = getFocusable(node);
        if (els.length === 0) {
          e.preventDefault();
          node.focus();
          return;
        }
        const first = els[0];
        const last = els[els.length - 1];
        const current = document.activeElement;
        if (!node.contains(current)) {
          // Focus already drifted outside the dialog (see above) — snap
          // it back in instead of letting Tab continue into the page.
          e.preventDefault();
          (e.shiftKey ? last : first).focus();
        } else if (e.shiftKey && current === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && current === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    // Belt-and-braces alongside the Tab handling above: if focus lands
    // outside the dialog for any reason while it's open (not just via Tab —
    // e.g. the browser's automatic fallback-to-body when the focused node
    // is unmounted), pull it back inside as soon as that happens rather
    // than waiting for the next keypress.
    const handleFocusIn = (e) => {
      if (!node.contains(e.target)) {
        const els = getFocusable(node);
        (els[0] || node).focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('focusin', handleFocusIn);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('focusin', handleFocusIn);
      if (triggerEl && typeof triggerEl.focus === 'function') {
        triggerEl.focus();
      }
    };
  }, []);

  return (
    <div onClick={onClose} className={className} style={style}>
      <div
        ref={contentRef}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        aria-labelledby={labelledBy}
        tabIndex={-1}
        className={contentClassName}
        style={contentStyle}
      >
        {children}
      </div>
    </div>
  );
}
