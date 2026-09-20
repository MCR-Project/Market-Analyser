/**
 * downloadFile - hand text to the browser to save as a file.
 *
 * Built in memory and released afterwards, so nothing goes near a server and
 * nothing stays allocated. Kept out of the modules that decide *what* a file
 * says (portfolioBackup.js) so those stay free of the DOM and can be tested
 * without one.
 */
export function downloadFile({ filename, text }, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Not revoked in the same tick: some browsers start the download after
  // the click handler returns, and would find the URL already gone.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
