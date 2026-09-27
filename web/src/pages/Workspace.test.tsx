import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { completedDocument } from "../test/documentFixtures";

const api = vi.hoisted(() => ({
  getCorpusRebuild: vi.fn(),
  getDocument: vi.fn(),
  listDocuments: vi.fn(),
  retryDocument: vi.fn(),
  uploadDocuments: vi.fn(),
}));

vi.mock("../api/client", () => ({
  getCorpusRebuild: api.getCorpusRebuild,
  getDocument: api.getDocument,
  listDocuments: api.listDocuments,
  retryDocument: api.retryDocument,
  uploadDocuments: api.uploadDocuments,
}));

// T051: the source library is wrapped in the provider-disclosure gate, so these tests stand in for an
// already-acknowledged workspace and keep asserting the page itself. The gate's own behaviour lives
// in `ProviderDisclosure.test.tsx`.
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
  const result = render(<Workspace />);
  // T051: the page is wrapped in the provider-disclosure gate, which fetches the disclosure on
  // mount. Flush that resolved promise so these tests exercise the page, not the gate's "checking"
  // state. Deliberately not `findBy*`: the polling tests install fake timers before rendering, and
  // RTL's `waitFor` then waits on a timer that never runs (the test hangs to its timeout).
  await act(async () => {});
  await act(async () => {});
  return result;
}

beforeEach(() => {
  // No rebuild has run for this workspace (404), which `CorpusRebuildBanner`
  // renders as nothing. The banner's own behaviour is covered in
  // `CorpusRebuildBanner.test.tsx`.
  api.getCorpusRebuild.mockRejectedValue({
    status: 404,
    code: "corpus_rebuild_not_found",
  });
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("Workspace", () => {
  it("accepts supported files and explains parser limitations", async () => {
    api.listDocuments.mockResolvedValue({ items: [] });

    await renderWorkspace();

    expect(screen.getByLabelText(/upload documents/i)).toHaveAttribute(
      "accept",
      ".md,.txt,.pdf,.docx",
    );
    expect(screen.getByText(/\.md, \.txt, \.pdf, and \.docx/i)).toBeVisible();
    expect(screen.getByText(/scanned PDFs require OCR/i)).toBeVisible();
    expect(screen.getByText(/password-protected PDFs/i)).toBeVisible();
    expect(screen.getByText(/corrupt files cannot be indexed/i)).toBeVisible();
  });

  it("shows upload progress while a document is being sent", async () => {
    api.listDocuments.mockResolvedValue({ items: [] });
    api.uploadDocuments.mockImplementation(
      (_files: File[], onProgress: (progress: number) => void) => {
        onProgress(40);
        return new Promise(() => undefined);
      },
    );
    const user = userEvent.setup();
    await renderWorkspace();

    await user.upload(
      screen.getByLabelText(/upload documents/i),
      new File(["# Notes"], "notes.md", { type: "text/markdown" }),
    );

    expect(api.uploadDocuments).toHaveBeenCalledOnce();
    expect(screen.getByText(/uploading.*40%/i)).toBeVisible();
  });

  it("polls non-terminal jobs every two seconds and stops at completion", async () => {
    vi.useFakeTimers();
    api.listDocuments
      .mockResolvedValueOnce({
        items: [
          {
            ...completedDocument,
            status: "running",
            stage: "extracting",
            progress: 55,
          },
        ],
      })
      .mockResolvedValueOnce({ items: [completedDocument] });

    await renderWorkspace();
    await act(async () => Promise.resolve());
    expect(api.listDocuments).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(api.listDocuments).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/^indexed$/i)).toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000);
    });
    expect(api.listDocuments).toHaveBeenCalledTimes(2);
  });

  it("cancels ingestion polling when the screen unmounts", async () => {
    vi.useFakeTimers();
    api.listDocuments.mockResolvedValue({
      items: [
        {
          ...completedDocument,
          status: "pending",
          stage: "queued",
          progress: 0,
        },
      ],
    });

    const view = await renderWorkspace();
    await act(async () => Promise.resolve());
    expect(api.listDocuments).toHaveBeenCalledTimes(1);
    view.unmount();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000);
    });
    expect(api.listDocuments).toHaveBeenCalledTimes(1);
  });

  it("shows extracted metadata, checksum state, decisions, and document link", async () => {
    api.listDocuments.mockResolvedValue({
      items: [
        completedDocument,
        {
          ...completedDocument,
          id: "document-2",
          display_name: "unchanged.txt",
          title: "Unchanged Notes",
          document_date: null,
          participants: [],
          source_type: null,
          project: null,
          modification_state: "unchanged",
          decision_count: 0,
        },
      ],
    });

    await renderWorkspace();

    expect(await screen.findByText("Authentication Review")).toBeVisible();
    expect(screen.getByText("2026-07-15")).toBeVisible();
    expect(screen.getByText("Asha, Mateo")).toBeVisible();
    expect(screen.getByText("meeting_notes")).toBeVisible();
    expect(screen.getByText("Atlas")).toBeVisible();
    expect(screen.getByText("Modified")).toBeVisible();
    expect(screen.getByText("Unchanged")).toBeVisible();
    expect(screen.getByText("3 decisions")).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: /view source: authentication-review\.md/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders parser-specific errors and retries retryable failures", async () => {
    api.listDocuments.mockResolvedValue({
      items: [
        {
          ...completedDocument,
          id: "empty-pdf",
          display_name: "scan.pdf",
          status: "failed",
          error: { code: "pdf_no_extractable_text", retryable: false },
        },
        {
          ...completedDocument,
          id: "protected-pdf",
          display_name: "protected.pdf",
          status: "failed",
          error: { code: "pdf_password_protected", retryable: false },
        },
        {
          ...completedDocument,
          id: "broken-docx",
          display_name: "broken.docx",
          status: "failed",
          error: { code: "docx_parse_failed", retryable: true },
        },
      ],
    });
    api.retryDocument.mockResolvedValue(undefined);
    const user = userEvent.setup();

    await renderWorkspace();

    expect(await screen.findByText(/contains no readable text/i)).toBeVisible();
    expect(
      screen.getByText(/^This password-protected PDF cannot be indexed\.$/i),
    ).toBeVisible();
    expect(screen.getByText(/DOCX file is corrupt/i)).toBeVisible();
    await user.click(screen.getByRole("button", { name: /retry broken\.docx/i }));

    await waitFor(() =>
      expect(api.retryDocument).toHaveBeenCalledWith("broken-docx"),
    );
  });

  it("views document source in-app through the authenticated client", async () => {
    api.listDocuments.mockResolvedValue({ items: [completedDocument] });
    api.getDocument.mockResolvedValue({
      id: completedDocument.id,
      display_name: completedDocument.display_name,
      media_type: completedDocument.media_type,
      active_version: null,
      status: "completed",
      stage: "completed",
      progress: 100,
      error: null,
      passages: [
        {
          sequence_number: 0,
          content: "Authentication was postponed until the import flow is stable.",
          locator: { kind: "lines", start: 1, end: 1 },
          structural_metadata: {
            group_path: [],
            block_types: ["paragraph"],
          },
        },
      ],
    });
    const user = userEvent.setup();
    await renderWorkspace();

    await user.click(
      await screen.findByRole("button", {
        name: /view source: authentication-review\.md/i,
      }),
    );

    expect(api.getDocument).toHaveBeenCalledWith(completedDocument.id);
    expect(
      await screen.findByText(/Authentication was postponed until the import flow/i),
    ).toBeVisible();
  });

  it("closes the source viewer from its close button", async () => {
    api.listDocuments.mockResolvedValue({ items: [completedDocument] });
    api.getDocument.mockResolvedValue({
      id: completedDocument.id,
      display_name: completedDocument.display_name,
      media_type: completedDocument.media_type,
      active_version: null,
      status: "completed",
      stage: "completed",
      progress: 100,
      error: null,
      passages: [
        {
          sequence_number: 0,
          content: "Authentication was postponed.",
          locator: { kind: "lines", start: 1, end: 1 },
          structural_metadata: {},
        },
      ],
    });
    const user = userEvent.setup();
    await renderWorkspace();

    await user.click(
      await screen.findByRole("button", {
        name: /view source: authentication-review\.md/i,
      }),
    );
    await screen.findByRole("dialog");

    await user.click(
      screen.getByRole("button", { name: /close source viewer/i }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("retries a failed document from the source viewer (T025)", async () => {
    const failedDocument = {
      ...completedDocument,
      id: "broken-docx",
      display_name: "broken.docx",
      status: "failed",
      error: { code: "docx_parse_failed", retryable: true },
    };
    api.listDocuments.mockResolvedValue({ items: [failedDocument] });
    api.getDocument.mockResolvedValue({
      id: failedDocument.id,
      display_name: failedDocument.display_name,
      media_type: failedDocument.media_type,
      active_version: null,
      status: "failed",
      stage: "failed",
      progress: 40,
      error: { code: "docx_parse_failed", retryable: true },
      passages: [],
    });
    api.retryDocument.mockResolvedValue(undefined);
    const user = userEvent.setup();

    await renderWorkspace();

    await user.click(
      await screen.findByRole("button", { name: /view source: broken\.docx/i }),
    );
    const dialog = await screen.findByRole("dialog");

    await user.click(
      within(dialog).getByRole("button", { name: /retry broken\.docx/i }),
    );

    await waitFor(() =>
      expect(api.retryDocument).toHaveBeenCalledWith("broken-docx"),
    );
  });

  it("refreshes the open detail view after retry so a second retry cannot fire (V94)", async () => {
    const failedDocument = {
      ...completedDocument,
      id: "broken-docx",
      display_name: "broken.docx",
      status: "failed",
      error: { code: "docx_parse_failed", retryable: true },
    };
    api.listDocuments.mockResolvedValue({ items: [failedDocument] });
    api.getDocument
      .mockResolvedValueOnce({
        id: failedDocument.id,
        display_name: failedDocument.display_name,
        media_type: failedDocument.media_type,
        active_version: null,
        status: "failed",
        stage: "failed",
        progress: 40,
        error: { code: "docx_parse_failed", retryable: true },
        passages: [],
      })
      .mockResolvedValueOnce({
        id: failedDocument.id,
        display_name: failedDocument.display_name,
        media_type: failedDocument.media_type,
        active_version: null,
        status: "pending",
        stage: "queued",
        progress: 0,
        error: null,
        passages: [],
      });
    api.retryDocument.mockResolvedValue(undefined);
    const user = userEvent.setup();

    await renderWorkspace();

    await user.click(
      await screen.findByRole("button", { name: /view source: broken\.docx/i }),
    );
    const dialog = await screen.findByRole("dialog");
    within(dialog).getByRole("button", { name: /retry broken\.docx/i });

    await user.click(
      within(dialog).getByRole("button", { name: /retry broken\.docx/i }),
    );

    await waitFor(() => expect(api.getDocument).toHaveBeenCalledTimes(2));
    expect(
      within(dialog).queryByRole("button", { name: /retry broken\.docx/i }),
    ).not.toBeInTheDocument();
    expect(api.retryDocument).toHaveBeenCalledTimes(1);
  });
});
