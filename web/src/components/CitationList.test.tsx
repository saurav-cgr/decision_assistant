import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { CitationList } from "./CitationList";

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
          locator: { kind: "pdf_region", page: 3, bbox: [0.1, 0.2, 0.8, 0.9] },
          equivalent_sources: [],
        },
      ]}
    />,
  );

  expect(screen.getByRole("button", { name: "evidence.pdf, page 3" })).toBeVisible();
});
