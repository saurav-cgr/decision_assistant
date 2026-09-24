import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({ getDocument: vi.fn() }));

import { CitationList } from "./CitationList";

describe("CitationList", () => {
  it("keeps the legacy PDF page citation label", () => {
    render(
      <CitationList
        citations={[
          {
            passage_id: "passage-1",
            quote: "Authentication was postponed.",
            start_offset: 0,
            end_offset: 31,
            content_hash: "a".repeat(64),
            document_id: "document-1",
            document_name: "decisions.pdf",
            locator: { kind: "pdf_page", page: 2 },
            equivalent_sources: [],
          },
        ]}
      />,
    );

    expect(
      screen.getByRole("button", { name: "decisions.pdf, page 2" }),
    ).toBeVisible();
  });

  it("labels PDF regions by page without visual highlighting", () => {
    render(
      <CitationList
        citations={[
          {
            passage_id: "passage-1",
            quote: "Evidence",
            start_offset: 0,
            end_offset: 8,
            content_hash: "0".repeat(64),
            document_id: "document-1",
            document_name: "evidence.pdf",
            locator: {
              kind: "pdf_region",
              page: 3,
              bbox: [0.1, 0.2, 0.8, 0.9],
            },
            equivalent_sources: [],
          },
        ]}
      />,
    );

    expect(
      screen.getByRole("button", { name: "evidence.pdf, page 3" }),
    ).toBeVisible();
  });
});
