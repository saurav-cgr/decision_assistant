import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { SourceViewer } from "./SourceViewer";

it("keeps keyboard focus inside source viewer", async () => {
  const user = userEvent.setup();
  render(
    <SourceViewer
      document={{
        id: "document-1",
        display_name: "notes.md",
        media_type: "text/markdown",
        active_version: null,
        passages: [],
      }}
      onClose={vi.fn()}
    />,
  );

  const close = screen.getByRole("button", { name: /close source viewer/i });
  expect(close).toHaveFocus();
  await user.tab();
  expect(close).toHaveFocus();
});
