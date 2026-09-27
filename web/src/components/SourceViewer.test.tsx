import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { DocumentDetail } from "../api/types";
import { SourceViewer } from "./SourceViewer";

const baseDocument: DocumentDetail = {
  id: "document-1",
  display_name: "notes.md",
  media_type: "text/markdown",
  active_version: null,
  passages: [],
  status: "completed",
  stage: "completed",
  progress: 100,
  error: null,
};

it("keeps keyboard focus inside source viewer", async () => {
  const user = userEvent.setup();
  render(<SourceViewer document={baseDocument} onClose={vi.fn()} />);

  const close = screen.getByRole("button", { name: /close source viewer/i });
  expect(close).toHaveFocus();
  await user.tab();
  expect(close).toHaveFocus();
});

it("shows a retry button for a retryable failed document and calls onRetry", async () => {
  const user = userEvent.setup();
  const onRetry = vi.fn();
  render(
    <SourceViewer
      document={{
        ...baseDocument,
        status: "failed",
        stage: "failed",
        progress: 40,
        error: { code: "provider_unavailable", message: "Provider unavailable" },
      }}
      onClose={vi.fn()}
      onRetry={onRetry}
      retryingId={null}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent(/failed/i);
  const retry = screen.getByRole("button", { name: /retry notes\.md/i });
  await user.click(retry);
  expect(onRetry).toHaveBeenCalledWith("document-1");
});

it("does not show a retry button for a non-retryable failed document", () => {
  render(
    <SourceViewer
      document={{
        ...baseDocument,
        status: "failed",
        stage: "failed",
        error: { code: "unsupported_file_type", message: "Unsupported" },
      }}
      onClose={vi.fn()}
      onRetry={vi.fn()}
    />,
  );

  expect(
    screen.queryByRole("button", { name: /retry notes\.md/i }),
  ).not.toBeInTheDocument();
});
