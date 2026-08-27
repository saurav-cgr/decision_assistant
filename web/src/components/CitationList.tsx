import { useState } from "react";

import { getDocument } from "../api/client";
import type { DocumentDetail, SourceCitation } from "../api/types";
import { SourceViewer } from "./SourceViewer";

type CitationListProps = {
  citations: SourceCitation[];
};

function locatorLabel(locator: SourceCitation["locator"]): string {
  if (locator.kind === "lines") {
    const start = locator.start;
    const end = locator.end;
    return start === end ? `line ${start}` : `lines ${start}–${end}`;
  }
  if (locator.kind === "pdf_page") return `page ${locator.page}`;
  if (locator.kind === "docx_paragraph") return `paragraph ${locator.paragraph}`;
  if (locator.kind === "docx_table") {
    return `table ${locator.table}, row ${locator.row}`;
  }
  return "source passage";
}

export function CitationList({ citations }: CitationListProps) {
  const [sourceDocument, setSourceDocument] = useState<DocumentDetail | null>(
    null,
  );
  const [sourceError, setSourceError] = useState<string | null>(null);

  if (citations.length === 0) return null;

  const handleViewSource = async (documentId: string) => {
    setSourceError(null);
    try {
      setSourceDocument(await getDocument(documentId));
    } catch (error) {
      setSourceError(
        error instanceof Error ? error.message : "Source could not be loaded.",
      );
    }
  };

  return (
    <section className="citation-section" aria-labelledby="citations-title">
      <div className="section-heading">
        <p className="eyebrow">Authoritative evidence</p>
        <h2 id="citations-title">Citations</h2>
      </div>
      <ol className="citation-list" aria-label="Citations">
        {citations.map((citation, index) => {
          const location = locatorLabel(citation.locator);
          const equivalentSources = citation.equivalent_sources ?? [];
          return (
            <li id={`citation-${index + 1}`} key={`${citation.passage_id}-${index}`}>
              <span className="citation-number" aria-hidden="true">
                {index + 1}
              </span>
              <blockquote>{citation.quote}</blockquote>
              <button
                type="button"
                className="citation-source"
                onClick={() => handleViewSource(citation.document_id)}
                aria-label={`${citation.document_name}, ${location}`}
              >
                {citation.document_name} · {location}
              </button>
              {equivalentSources.filter(
                (source) => source.passage_id !== citation.passage_id,
              ).length > 0 && (
                <ul aria-label="Equivalent sources">
                  {equivalentSources
                    .filter((source) => source.passage_id !== citation.passage_id)
                    .map((source) => (
                      <li key={source.passage_id}>
                        <button
                          type="button"
                          className="citation-source"
                          onClick={() => handleViewSource(source.document_id)}
                          aria-label={`${source.document_name}, ${locatorLabel(source.locator)}`}
                        >
                          Also in {source.document_name} · {locatorLabel(source.locator)}
                        </button>
                      </li>
                    ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
      {sourceError && (
        <p className="citation-error" role="alert">
          {sourceError}
        </p>
      )}
      {sourceDocument && (
        <SourceViewer
          document={sourceDocument}
          onClose={() => setSourceDocument(null)}
        />
      )}
    </section>
  );
}
