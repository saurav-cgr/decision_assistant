import type { DocumentListItem } from "../api/types";
import { IngestionStatus } from "./IngestionStatus";

type DocumentTableProps = {
  documents: DocumentListItem[];
  emptyMessage?: string;
  retryingId: string | null;
  onRetry: (documentId: string) => void;
  onUploadRequest?: () => void;
  onViewSource: (document: DocumentListItem) => void;
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
  emptyMessage = "No source documents yet",
  retryingId,
  onRetry,
  onUploadRequest,
  onViewSource,
}: DocumentTableProps) {
  if (documents.length === 0) {
    return (
      <div className="workspace-empty">
        <h2>{emptyMessage}</h2>
        <p>
          {emptyMessage === "No source documents yet"
            ? "Upload project notes to begin building decision memory."
            : "Try a different search or status filter."}
        </p>
        {onUploadRequest && emptyMessage === "No source documents yet" && (
          <button type="button" className="workspace-empty__action" onClick={onUploadRequest}>
            Upload first source
          </button>
        )}
      </div>
    );
  }

  return (
    <section aria-labelledby="document-list-title">
      <div className="document-list__heading">
        <div>
          <p className="eyebrow">Indexed evidence</p>
          <h2 id="document-list-title">Sources</h2>
        </div>
        <span>{documents.length} {documents.length === 1 ? "source" : "sources"}</span>
      </div>
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
            <button
              type="button"
              className="document-card__source"
              onClick={() => onViewSource(document)}
              aria-label={`View source: ${document.display_name}`}
            >
              View source
            </button>
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
    </section>
  );
}
