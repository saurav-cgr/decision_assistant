import { documentDetailUrl } from "../api/client";
import type { DocumentListItem } from "../api/types";
import { IngestionStatus } from "./IngestionStatus";

type DocumentTableProps = {
  documents: DocumentListItem[];
  retryingId: string | null;
  onRetry: (documentId: string) => void;
};

const retryableErrorCodes = new Set([
  "ingestion_interrupted",
  "provider_unavailable",
]);

function displayValue(value: string | null): string {
  return value || "Not extracted";
}

function displayModificationState(
  state: DocumentListItem["modification_state"],
): string {
  if (!state) return "Pending";
  return `${state.charAt(0).toUpperCase()}${state.slice(1)}`;
}

function canRetry(document: DocumentListItem): boolean {
  return Boolean(
    document.error?.retryable ||
      (document.error?.code && retryableErrorCodes.has(document.error.code)),
  );
}

export function DocumentTable({
  documents,
  retryingId,
  onRetry,
}: DocumentTableProps) {
  if (documents.length === 0) {
    return (
      <div className="workspace-empty">
        <h2>No source documents yet</h2>
        <p>Upload project notes to begin building decision memory.</p>
      </div>
    );
  }

  return (
    <div className="document-list" aria-label="Workspace documents">
      {documents.map((document) => (
        <article className="document-card" key={document.id}>
          <div className="document-card__heading">
            <div>
              <p className="document-card__type">{document.media_type}</p>
              <h2>{document.title || document.display_name}</h2>
              {document.title && (
                <p className="document-card__filename">{document.display_name}</p>
              )}
            </div>
            <IngestionStatus
              error={document.error}
              progress={document.progress}
              stage={document.stage}
              status={document.status}
            />
          </div>

          <dl className="document-metadata">
            <div>
              <dt>Date</dt>
              <dd>{displayValue(document.document_date)}</dd>
            </div>
            <div>
              <dt>Participants</dt>
              <dd>
                {document.participants.length > 0
                  ? document.participants.join(", ")
                  : "Not extracted"}
              </dd>
            </div>
            <div>
              <dt>Source type</dt>
              <dd>{displayValue(document.source_type)}</dd>
            </div>
            <div>
              <dt>Project</dt>
              <dd>{displayValue(document.project)}</dd>
            </div>
          </dl>

          <div className="document-card__footer">
            <span className="state-badge">
              {displayModificationState(document.modification_state)}
            </span>
            <span>
              {document.decision_count}{" "}
              {document.decision_count === 1 ? "decision" : "decisions"}
            </span>
            <a
              href={documentDetailUrl(document.id)}
              target="_blank"
              rel="noreferrer"
              aria-label={`View ${document.display_name}`}
            >
              View source
            </a>
            {document.status === "failed" && canRetry(document) && (
              <button
                type="button"
                disabled={retryingId === document.id}
                onClick={() => onRetry(document.id)}
                aria-label={`Retry ${document.display_name}`}
              >
                {retryingId === document.id ? "Retrying…" : "Retry"}
              </button>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
