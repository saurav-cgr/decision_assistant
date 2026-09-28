import { useEffect, useState } from "react";

import { getCorpusRebuild, retryCorpusRebuild } from "../api/client";
import type { CorpusRebuildStatus } from "../api/types";

import "./CorpusRebuildBanner.css";

const DEFAULT_POLL_INTERVAL_MS = 2_000;

type Props = {
  /** Poll cadence while a rebuild is `pending`/`running`. */
  pollIntervalMs?: number;
};

/**
 * The HTTP status of a thrown API error, without depending on the
 * `ApiClientError` class *identity*: pages that mock `../api/client` partially
 * (as `Workspace.test.tsx` does) would otherwise make `instanceof` throw a
 * `TypeError` from inside this catch block.
 */
function errorStatus(caught: unknown): number | null {
  if (typeof caught !== "object" || caught === null) return null;
  const status = (caught as { status?: unknown }).status;
  return typeof status === "number" ? status : null;
}

function progressLabel(rebuild: CorpusRebuildStatus): string {
  const { documents_completed: completed, documents_total: total } = rebuild;
  if (rebuild.status === "pending" || total === 0) {
    return "Rebuilding the corpus · starting…";
  }
  return `Rebuilding the corpus · ${completed}/${total} documents`;
}

/**
 * T032: the workspace's corpus-rebuild progress.
 *
 * A rebuild is the app's own upgrade path (a changed chunking/embedding/parser
 * profile re-ingests every document), so it can take minutes and the operator
 * needs to see it happening — `GET /workspaces/{id}/corpus-rebuild` reports
 * `documents_completed`/`documents_total` while the work runs, in a
 * transaction of its own. A `failed` rebuild is all-or-nothing (the old corpus
 * is left intact), so the banner offers the retry the API exposes.
 *
 * Renders nothing until a rebuild exists: a workspace that has never run one
 * answers 404 `corpus_rebuild_not_found`, and "no rebuild" is not a failure to
 * report. The same silence covers a missing/expired session — there is no
 * action a reader could take on a banner about it here.
 */
export function CorpusRebuildBanner({ pollIntervalMs = DEFAULT_POLL_INTERVAL_MS }: Props) {
  const [rebuild, setRebuild] = useState<CorpusRebuildStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [pollToken, setPollToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const status = await getCorpusRebuild();
        if (cancelled) return;
        setRebuild(status);
        setError(null);
        if (status.status === "pending" || status.status === "running") {
          timer = setTimeout(poll, pollIntervalMs);
        }
      } catch (caught) {
        if (cancelled) return;
        const status = errorStatus(caught);
        if (status !== null && status < 500) {
          // 404: no rebuild has ever run for this workspace. 401/403/409: the
          // banner is not the place to explain it.
          setRebuild(null);
          return;
        }
        setError(
          caught instanceof Error
            ? caught.message
            : "Rebuild status could not be loaded.",
        );
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [pollIntervalMs, pollToken]);

  const handleRetry = async () => {
    setRetrying(true);
    setError(null);
    try {
      await retryCorpusRebuild();
      // Restart polling from a clean effect run so the retry's progress is
      // picked up even if the previous run had stopped polling.
      setPollToken((token) => token + 1);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Rebuild retry failed.",
      );
    } finally {
      setRetrying(false);
    }
  };

  if (!rebuild) {
    if (!error) return null;
    return (
      <p className="corpus-rebuild corpus-rebuild--error" role="alert">
        {error}
      </p>
    );
  }

  if (rebuild.status === "failed") {
    const code =
      typeof rebuild.error?.code === "string" ? rebuild.error.code : "rebuild_failed";
    return (
      <div className="corpus-rebuild corpus-rebuild--error" role="alert">
        <span>
          Corpus rebuild failed ({code}). Your existing documents and decisions
          are unchanged.
        </span>
        <button type="button" onClick={handleRetry} disabled={retrying}>
          {retrying ? "Retrying…" : "Retry rebuild"}
        </button>
        {error && <span className="corpus-rebuild__detail">{error}</span>}
      </div>
    );
  }

  if (rebuild.status === "completed") {
    return (
      <p className="corpus-rebuild corpus-rebuild--done" role="status">
        Corpus rebuild complete · {rebuild.documents_completed}/
        {rebuild.documents_total} documents
      </p>
    );
  }

  return (
    <p className="corpus-rebuild" role="status" aria-live="polite">
      {progressLabel(rebuild)}
    </p>
  );
}
