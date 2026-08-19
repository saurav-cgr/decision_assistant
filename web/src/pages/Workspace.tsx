import { useEffect, useRef, useState } from "react";

import {
  getDocument,
  listDocuments,
  retryDocument,
  uploadDocuments,
} from "../api/client";
import type { DocumentDetail, DocumentListItem } from "../api/types";
import { DocumentTable } from "../components/DocumentTable";
import { SourceViewer } from "../components/SourceViewer";

const POLL_INTERVAL_MS = 2_000;

function hasNonTerminalJobs(documents: DocumentListItem[]): boolean {
  return documents.some(
    (document) =>
      document.status === "pending" || document.status === "running",
  );
}

export function Workspace() {
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [sourceDocument, setSourceDocument] = useState<DocumentDetail | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;

    const refresh = async () => {
      try {
        const response = await listDocuments();
        if (cancelled) return;
        setDocuments(response.items);
        setLoadError(null);
        if (hasNonTerminalJobs(response.items)) {
          pollTimer = setTimeout(refresh, POLL_INTERVAL_MS);
        }
      } catch (error) {
        if (!cancelled) {
          setLoadError(
            error instanceof Error ? error.message : "Documents could not be loaded.",
          );
        }
      }
    };

    void refresh();
    return () => {
      cancelled = true;
      if (pollTimer !== undefined) clearTimeout(pollTimer);
    };
  }, [refreshVersion]);

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (files.length === 0) return;

    setUploadError(null);
    setUploadProgress(0);
    try {
      const response = await uploadDocuments(files, setUploadProgress);
      const rejected = response.results.filter((result) => result.status === "rejected");
      if (rejected.length > 0) {
        setUploadError(
          rejected.map((result) => `${result.filename}: ${result.error?.message}`).join(" "),
        );
      }
      setUploadProgress(null);
      setRefreshVersion((version) => version + 1);
    } catch (error) {
      setUploadProgress(null);
      setUploadError(
        error instanceof Error ? error.message : "Upload failed. Please try again.",
      );
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleRetry = async (documentId: string) => {
    setRetryingId(documentId);
    setLoadError(null);
    try {
      await retryDocument(documentId);
      setRefreshVersion((version) => version + 1);
    } catch (error) {
      setLoadError(
        error instanceof Error ? error.message : "Ingestion retry failed.",
      );
    } finally {
      setRetryingId(null);
    }
  };

  const handleViewSource = async (document: DocumentListItem) => {
    setSourceError(null);
    try {
      const detail = await getDocument(document.id);
      setSourceDocument(detail);
    } catch (error) {
      setSourceError(
        error instanceof Error ? error.message : "Source could not be loaded.",
      );
    }
  };

  return (
    <section className="workspace-page" aria-labelledby="workspace-title">
      <div className="workspace-header">
        <div>
          <p className="eyebrow">Source library</p>
          <h1 id="workspace-title">Workspace</h1>
          <p className="page-description">
            Index project records, inspect extraction status, and trace every
            decision back to its source.
          </p>
        </div>

        <label className="upload-control">
          <span>Upload documents</span>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".md,.txt,.pdf,.docx"
            onChange={handleUpload}
            aria-label="Upload documents"
          />
        </label>
      </div>

      <aside className="upload-guidance" aria-label="Supported document formats">
        <strong>Supported: .md, .txt, .pdf, and .docx</strong>
        <span>
          Scanned PDFs require OCR; password-protected PDFs and corrupt files
          cannot be indexed.
        </span>
      </aside>

      {uploadProgress !== null && (
        <p className="workspace-notice" role="status">
          Uploading documents · {uploadProgress}%
        </p>
      )}
      {uploadError && (
        <p className="workspace-notice workspace-notice--error" role="alert">
          {uploadError}
        </p>
      )}
      {loadError && (
        <p className="workspace-notice workspace-notice--error" role="alert">
          {loadError}
        </p>
      )}
      {sourceError && (
        <p className="workspace-notice workspace-notice--error" role="alert">
          {sourceError}
        </p>
      )}

      <DocumentTable
        documents={documents}
        retryingId={retryingId}
        onRetry={handleRetry}
        onViewSource={handleViewSource}
      />
      {sourceDocument && (
        <SourceViewer
          document={sourceDocument}
          onClose={() => setSourceDocument(null)}
        />
      )}
    </section>
  );
}
