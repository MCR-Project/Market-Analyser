/**
 * ImportBackupButton — a button that opens the file picker for a Backup
 * (issue #148).
 *
 * Shared by the sidebar and the landing page, which want the same action
 * dressed differently: the caller supplies the classes and the label, and
 * this owns the one thing that has to be right, which is the input.
 *
 * A file picker only. No drag-and-drop and no paste box: each would be
 * another way in to validate, and the raw-list case is already a file.
 *
 * The input is cleared as soon as its file has been taken, because a
 * `change` event does not fire for the file that was picked last time -
 * without it, importing the same file twice (the second time is the
 * "everything was skipped" answer) would do nothing at all.
 */
import { useRef } from 'react';

export function ImportBackupButton({ onFile, className, children, title }) {
  const input = useRef(null);
  return (
    <>
      <button
        type="button"
        onClick={() => input.current?.click()}
        title={title}
        className={className}
      >
        {children}
      </button>
      <input
        ref={input}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) onFile(file);
        }}
      />
    </>
  );
}
