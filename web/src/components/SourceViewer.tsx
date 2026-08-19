import { useEffect, useRef } from "react";

import type { DocumentDetail } from "../api/types";

type SourceViewerProps = {
  document: DocumentDetail;
  onClose: () => void;
};

export function SourceViewer({ document, onClose }: SourceViewerProps) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Use `window` (not `document`) because the `document` prop shadows the
    // global DOM document inside this component.
    const previous = window.document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      previous?.focus?.();
    };
  }, [onClose]);

  return (
    <div className="source-viewer-backdrop" onClick={onClose}>
      <section
        className="source-viewer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="source-viewer-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="source-viewer__header">
          <div>
            <p className="eyebrow">{document.media_type}</p>
            <h2 id="source-viewer-title">
              {document.active_version?.title || document.display_name}
            </h2>
            <p className="document-card__filename">{document.display_name}</p>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="source-viewer__close"
            onClick={onClose}
            aria-label="Close source viewer"
          >
            Close
          </button>
        </header>
        <div className="source-viewer__body">
          {document.passages.length === 0 ? (
            <p className="source-viewer__empty">
              No source passages are available for this document.
            </p>
          ) : (
            document.passages.map((passage) => (
              <article
                className="source-passage"
                key={passage.sequence_number}
              >
                <p className="source-passage__meta">
                  Passage {passage.sequence_number + 1}
                </p>
                <pre className="source-passage__content">{passage.content}</pre>
              </article>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
