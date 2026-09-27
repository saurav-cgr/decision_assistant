import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  completedDocument,
  detailFixture,
  failedListItem,
} from "../test/documentFixtures";

const api = vi.hoisted(() => ({
  getDocument: vi.fn(),
  listDocuments: vi.fn(),
  retryDocument: vi.fn(),
  uploadDocuments: vi.fn(),
}));

vi.mock("../api/client", () => ({
  getDocument: api.getDocument,
  listDocuments: api.listDocuments,
  retryDocument: api.retryDocument,
  uploadDocuments: api.uploadDocuments,
}));

// T051: see `Workspace.test.tsx` — an acknowledged disclosure is what these tests assume.
vi.mock("../api/provider", () => ({
  getProviderDisclosure: vi.fn().mockResolvedValue({
    provider: "ollama",
    generation_provider: "ollama",
    embedding_provider: "ollama",
    generation_sends_document_text_remotely: false,
    embedding_sends_document_text_remotely: false,
    sends_document_text_remotely: false,
    acknowledged_at: "2026-09-26T00:00:00Z",
  }),
  acknowledgeProviderDisclosure: vi.fn(),
}));

async function renderWorkspace() {
  const modulePath = "./Workspace";
  const { Workspace } = await import(/* @vite-ignore */ modulePath);
  return render(<Workspace />);
}

// Holds the retry promise open so the test can change the open document while
// the retry is still in flight — the window V97 was found in.
function holdRetryOpen() {
  let resolveRetry: () => void = () => undefined;
  api.retryDocument.mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        resolveRetry = resolve;
      }),
  );
  return () => resolveRetry();
}

// A single microtask tick is not enough for the retry continuation (await
// retryDocument -> await getDocument -> setState) to finish, which would let
// these tests pass without ever reaching the guard they exist to check. The
// macrotask hop after resolving guarantees the whole chain has run.
async function finishRetry(resolveRetry: () => void) {
  await act(async () => {
    resolveRetry();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("Workspace retry refresh", () => {
  it("does not reopen a detail view closed while its retry was in flight (V97)", async () => {
    api.listDocuments.mockResolvedValue({
      items: [failedListItem("broken-docx", "broken.docx")],
    });
    api.getDocument.mockResolvedValue(
      detailFixture("broken-docx", "broken.docx", "failed"),
    );
    const resolveRetry = holdRetryOpen();
    const user = userEvent.setup();

    await renderWorkspace();

    await user.click(
      await screen.findByRole("button", { name: /view source: broken\.docx/i }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getByRole("button", { name: /retry broken\.docx/i }),
    );
    expect(api.retryDocument).toHaveBeenCalledWith("broken-docx");
    await user.click(
      screen.getByRole("button", { name: /close source viewer/i }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await finishRetry(resolveRetry);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.getDocument).toHaveBeenCalledTimes(1);
  });

  it("does not overwrite a different document opened during a retry (V97)", async () => {
    api.listDocuments.mockResolvedValue({
      items: [failedListItem("broken-docx", "broken.docx"), completedDocument],
    });
    api.getDocument.mockImplementation((id: string) =>
      Promise.resolve(
        id === "broken-docx"
          ? detailFixture("broken-docx", "broken.docx", "failed")
          : detailFixture(
              completedDocument.id,
              completedDocument.display_name,
              "completed",
            ),
      ),
    );
    const resolveRetry = holdRetryOpen();
    const user = userEvent.setup();

    await renderWorkspace();

    await user.click(
      await screen.findByRole("button", { name: /view source: broken\.docx/i }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getByRole("button", { name: /retry broken\.docx/i }),
    );
    await user.click(
      screen.getByRole("button", { name: /close source viewer/i }),
    );
    await user.click(
      screen.getByRole("button", {
        name: /view source: authentication-review\.md/i,
      }),
    );
    await screen.findByRole("dialog");

    await finishRetry(resolveRetry);

    expect(api.getDocument).toHaveBeenCalledTimes(2);
    expect(api.getDocument).toHaveBeenLastCalledWith(completedDocument.id);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("does not reopen when the viewer closes while the refresh fetch is in flight (V97)", async () => {
    api.listDocuments.mockResolvedValue({
      items: [failedListItem("broken-docx", "broken.docx")],
    });
    let resolveDetail: (detail: unknown) => void = () => undefined;
    api.getDocument
      .mockResolvedValueOnce(
        detailFixture("broken-docx", "broken.docx", "failed"),
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveDetail = resolve;
          }),
      );
    const resolveRetry = holdRetryOpen();
    const user = userEvent.setup();

    await renderWorkspace();

    await user.click(
      await screen.findByRole("button", { name: /view source: broken\.docx/i }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getByRole("button", { name: /retry broken\.docx/i }),
    );

    // The retry has resolved, so the refresh fetch has started and is still
    // pending when the viewer is closed.
    await finishRetry(resolveRetry);
    expect(api.getDocument).toHaveBeenCalledTimes(2);

    await user.click(
      screen.getByRole("button", { name: /close source viewer/i }),
    );
    await act(async () => {
      resolveDetail(detailFixture("broken-docx", "broken.docx", "pending"));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
