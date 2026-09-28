import { useEffect, useRef, useState } from "react";

import {
  getProviderDisclosure,
  providerSwitchPreview,
  switchProvider,
} from "../api/provider";
import type {
  ProviderName,
  ProviderSwitchPreview,
} from "../api/provider";
import { providerFailureMessage } from "./providerFailure";
import "./ProviderSettings.css";

const PROVIDERS: ProviderName[] = ["gemini", "ollama"];

/**
 * T052 (US6/FR-016): the provider switch, with the pending-rebuild confirmation FR-016 requires.
 *
 * The 409 from `POST /workspace/{id}/provider` is not an error state — it is the server asking for
 * confirmation — so it opens the dialog instead of an alert, and the numbers the dialog shows come
 * from that payload rather than a second client-side guess about what the profile change means.
 *
 * One honest limit: the disclosure reports both the active generation and embedding providers, but
 * it does not report the embedding *profile* a switch would change to; the confirmed configuration
 * is shown from the switch response. The selects pre-fill from the disclosure (V146/V147).
 */
export function ProviderSettings() {
  const [activeProvider, setActiveProvider] = useState<string | null>(null);
  const [generation, setGeneration] = useState<ProviderName>("gemini");
  const [embedding, setEmbedding] = useState<ProviderName>("gemini");
  const [preview, setPreview] = useState<ProviderSwitchPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancelled = false;
    getProviderDisclosure()
      .then((disclosure) => {
        if (cancelled) return;
        setActiveProvider(disclosure.generation_provider);
        const generation = disclosure.generation_provider as ProviderName;
        const embedding = disclosure.embedding_provider as ProviderName;
        if (PROVIDERS.includes(generation)) {
          setGeneration(generation);
        }
        if (PROVIDERS.includes(embedding)) {
          setEmbedding(embedding);
        }
      })
      .catch(() => {
        // Informational: the switch below reports its own failures.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (preview) confirmRef.current?.focus();
  }, [preview]);

  const submit = async (confirmRebuild: boolean) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await switchProvider({
        generation_provider: generation,
        embedding_provider: embedding,
        confirm_rebuild: confirmRebuild,
      });
      setPreview(null);
      setActiveProvider(result.generation_provider);
      const cleared = result.disclosure_acknowledgement_cleared
        ? " Document text now leaves this machine, so the data-handling acknowledgement was" +
          " cleared — uploads stay blocked until you acknowledge again."
        : "";
      setMessage(
        (result.rebuild
          ? `Switched to ${result.generation_provider}. Re-ingesting ${result.documents_total} document(s) in this workspace.`
          : `Switched to ${result.generation_provider} (embedding: ${result.embedding_provider}). No re-ingestion needed.`) +
          cleared,
      );
    } catch (caught) {
      const pending = providerSwitchPreview(caught);
      if (pending) {
        setPreview(pending);
      } else {
        setError(
          providerFailureMessage(caught) ??
            (caught instanceof Error ? caught.message : "The provider could not be switched."),
        );
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="provider-settings" aria-labelledby="provider-settings-title">
      <h2 id="provider-settings-title">Model provider</h2>
      <p className="provider-settings__current">
        Active generation provider:{" "}
        <strong>{activeProvider ?? "unknown"}</strong>
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit(false);
        }}
      >
        <label htmlFor="generation-provider">Generation provider</label>
        <select
          id="generation-provider"
          value={generation}
          onChange={(event) => setGeneration(event.target.value as ProviderName)}
        >
          {PROVIDERS.map((provider) => (
            <option key={provider} value={provider}>
              {provider}
            </option>
          ))}
        </select>
        <label htmlFor="embedding-provider">Embedding provider</label>
        <select
          id="embedding-provider"
          value={embedding}
          onChange={(event) => setEmbedding(event.target.value as ProviderName)}
        >
          {PROVIDERS.map((provider) => (
            <option key={provider} value={provider}>
              {provider}
            </option>
          ))}
        </select>
        <button type="submit" disabled={busy}>
          {busy ? "Switching…" : "Save provider"}
        </button>
      </form>

      {error && (
        <p className="auth-message auth-message--error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="auth-message" role="status">
          {message}
        </p>
      )}

      {preview && (
        <div
          className="provider-settings__dialog"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="provider-confirm-title"
          aria-describedby="provider-confirm-body"
        >
          <h3 id="provider-confirm-title">This switch re-ingests your documents</h3>
          <p id="provider-confirm-body">
            The provider choice is stored for the whole installation, so changing the embedding
            provider indexes documents again in every workspace, not only this one
            {preview.documentsTotal !== null
              ? ` (this workspace: ${preview.documentsTotal} document(s))`
              : ""}
            . Decisions and conversations are preserved.
          </p>
          {preview.workspaces.length > 0 && (
            <ul className="provider-settings__workspaces">
              {preview.workspaces.map((entry) => (
                <li key={entry.name}>
                  {entry.name}: {entry.documentsTotal} document(s)
                </li>
              ))}
            </ul>
          )}
          {preview.disclosureAcknowledgementWillBeCleared && (
            <p className="provider-settings__warning" role="note">
              This makes a provider send document text off this machine, so the data-handling
              acknowledgement is cleared and uploads stay blocked until you acknowledge again.
            </p>
          )}
          <dl className="provider-settings__profiles">
            <div>
              <dt>Current embedding profile</dt>
              <dd>{formatProfile(preview.currentEmbeddingProfile)}</dd>
            </div>
            <div>
              <dt>Proposed embedding profile</dt>
              <dd>{formatProfile(preview.proposedEmbeddingProfile)}</dd>
            </div>
          </dl>
          <div className="provider-settings__actions">
            <button
              ref={confirmRef}
              type="button"
              onClick={() => void submit(true)}
              disabled={busy}
            >
              {busy ? "Switching…" : "Switch and rebuild"}
            </button>
            <button type="button" onClick={() => setPreview(null)} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function formatProfile(profile: Record<string, unknown> | null): string {
  if (!profile) return "not reported";
  const provider = profile.provider;
  const model = profile.model;
  return [provider, model].filter((value) => typeof value === "string").join(" · ") ||
    "not reported";
}
