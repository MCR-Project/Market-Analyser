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
    (el) => el.offsetParent !== null
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
          return;
        }
        const first = els[0];
        const last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    node.addEventListener('keydown', handleKeyDown);
    return () => {
      node.removeEventListener('keydown', handleKeyDown);
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
