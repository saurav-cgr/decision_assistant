import { useState } from "react";

import { downloadDiagnosticsBundle } from "../api/client";

/**
 * T059 (US7/FR-018): a one-click diagnostics download on the settings page.
 *
 * The archive needs the bearer token, so it cannot be a plain `<a href>` — the client fetches it and
 * this hands the result to the browser as a blob download.
 */
export function saveBundleBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoked on the next tick rather than immediately: some browsers cancel a download whose object
  // URL is revoked in the same task as the click.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function DiagnosticsDownload() {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const download = async () => {
    setPending(true);
    setError(null);
    setMessage(null);
    try {
      const bundle = await downloadDiagnosticsBundle();
      saveBundleBlob(bundle.blob, bundle.filename);
      setMessage(`Diagnostics bundle saved as ${bundle.filename}.`);
    } catch (caught) {
      // A specific state, not a generic failure (FR-026): the message the API sends is what the
      // operator needs, and it never contains a secret.
      setError(
        caught instanceof Error ? caught.message : "Diagnostics bundle download failed",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <section className="diagnostics-download" aria-labelledby="diagnostics-download-title">
      <h2 id="diagnostics-download-title">Diagnostics</h2>
      <p id="diagnostics-download-description">
        Download a support bundle: recent logs, the applied database revision, the app version, and a
        sanitized configuration summary. Secret values are excluded.
      </p>
      <button
        type="button"
        onClick={() => void download()}
        disabled={pending}
        aria-describedby="diagnostics-download-description"
      >
        {pending ? "Preparing bundle…" : "Download diagnostics bundle"}
      </button>
      <p className="auth-message" role="status" aria-live="polite">
        {message}
      </p>
      {error && (
        <p className="auth-message auth-message--error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
