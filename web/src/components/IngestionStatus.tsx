import type { DocumentListItem } from "../api/types";
import { providerFailureText } from "./providerFailure";

const parserErrors: Record<string, string> = {
  pdf_no_extractable_text: "This PDF contains no readable text.",
  pdf_password_protected: "This password-protected PDF cannot be indexed.",
  pdf_parse_failed: "This PDF file is corrupt or could not be read.",
  docx_parse_failed: "This DOCX file is corrupt or could not be read.",
};

const retryableErrorCodes = new Set([
  "ingestion_interrupted",
  "provider_unavailable",
]);

type IngestionOutcome = Pick<DocumentListItem, "error" | "progress" | "stage" | "status">;

type IngestionStatusProps = IngestionOutcome;

// Shared by the document list (DocumentTable) and detail (SourceViewer)
// views — T024/T025 — so "is this failure retryable" has one definition,
// not a client-side judgment call duplicated per view.
export function canRetryDocument(document: IngestionOutcome): boolean {
  return Boolean(
    document.status === "failed" &&
      (document.error?.retryable ||
        (document.error?.code && retryableErrorCodes.has(document.error.code))),
  );
}

export function IngestionStatus({
  error,
  progress,
  stage,
  status,
}: IngestionStatusProps) {
  if (status === "failed") {
    // T067/FR-026: a provider failure (a rejected API key, an unreachable provider) is not a parser
    // problem, so it reads as its own actionable state instead of the parser table's or the raw
    // server string.
    const message =
      (error?.code && parserErrors[error.code]) ||
      providerFailureText(error?.code) ||
      error?.message ||
      "Indexing failed. Inspect the API logs for details.";
    return (
      <div className="ingestion-status ingestion-status--failed" role="alert">
        <strong>Failed</strong>
        <span>{message}</span>
      </div>
    );
  }

  if (status === "pending" || status === "running") {
    return (
      <div className="ingestion-status ingestion-status--working" role="status" aria-live="polite">
        <strong>{status === "pending" ? "Queued" : "Indexing"}</strong>
        <span>
          {stage || "Preparing"}
          {progress !== null ? ` · ${progress}%` : ""}
        </span>
      </div>
    );
  }

  if (status === "completed") {
    return (
      <div className="ingestion-status ingestion-status--complete" role="status">
        <strong>Indexed</strong>
        <span>{stage === "unchanged" ? "Content unchanged" : "Ready to search"}</span>
      </div>
    );
  }

  return (
    <div className="ingestion-status">
      <strong>Not indexed</strong>
      <span>Waiting for ingestion</span>
    </div>
  );
}
