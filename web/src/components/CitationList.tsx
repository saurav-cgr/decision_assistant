import { documentDetailUrl } from "../api/client";
import type { SourceCitation } from "../api/types";

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
  if (citations.length === 0) return null;

  return (
    <section className="citation-section" aria-labelledby="citations-title">
      <div className="section-heading">
        <p className="eyebrow">Authoritative evidence</p>
        <h2 id="citations-title">Citations</h2>
      </div>
      <ol className="citation-list" aria-label="Citations">
        {citations.map((citation, index) => {
          const location = locatorLabel(citation.locator);
          return (
            <li key={`${citation.passage_id}-${index}`}>
              <span className="citation-number" aria-hidden="true">
                {index + 1}
              </span>
              <blockquote>{citation.quote}</blockquote>
              <a
                href={documentDetailUrl(citation.document_id)}
                target="_blank"
                rel="noreferrer"
                aria-label={`${citation.document_name}, ${location}`}
              >
                {citation.document_name} · {location}
              </a>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
