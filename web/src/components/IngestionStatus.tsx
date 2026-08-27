import type { DocumentListItem } from "../api/types";

const parserErrors: Record<string, string> = {
  ocr_not_supported: "This scanned PDF requires OCR, which is not supported.",
  pdf_password_protected: "This password-protected PDF cannot be indexed.",
  pdf_parse_failed: "This PDF file is corrupt or could not be read.",
  docx_parse_failed: "This DOCX file is corrupt or could not be read.",
};

type IngestionStatusProps = Pick<
  DocumentListItem,
  "error" | "progress" | "stage" | "status"
>;

export function IngestionStatus({
  error,
  progress,
  stage,
  status,
}: IngestionStatusProps) {
  if (status === "failed") {
    const message =
      (error?.code && parserErrors[error.code]) ||
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
