import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  retryDocument: vi.fn(),
  uploadDocuments: vi.fn(),
}));

vi.mock("../api/client", () => ({
  documentDetailUrl: (documentId: string) =>
    `http://localhost:8000/api/v1/documents/${documentId}`,
  listDocuments: api.listDocuments,
  retryDocument: api.retryDocument,
  uploadDocuments: api.uploadDocuments,
}));

const completedDocument = {
  id: "document-1",
  display_name: "authentication-review.md",
  media_type: "text/markdown",
  active_version_id: "version-1",
  status: "completed",
  stage: "completed",
  progress: 100,
  error: null,
  title: "Authentication Review",
  document_date: "2026-07-15",
  participants: ["Asha", "Mateo"],
  source_type: "meeting_notes",
  project: "Atlas",
  modification_state: "modified",
  decision_count: 3,
};

async function renderWorkspace() {
  const modulePath = "./Workspace";
  const { Workspace } = await import(/* @vite-ignore */ modulePath);
  return render(<Workspace />);
}

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
      screen.getByRole("link", { name: /view authentication-review\.md/i }),
    ).toHaveAttribute(
      "href",
      "http://localhost:8000/api/v1/documents/document-1",
    );
  });

  it("renders parser-specific errors and retries retryable failures", async () => {
    api.listDocuments.mockResolvedValue({
      items: [
        {
          ...completedDocument,
          id: "ocr-pdf",
          display_name: "scan.pdf",
          status: "failed",
          error: { code: "ocr_not_supported", retryable: false },
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

    expect(await screen.findByText(/scanned PDF requires OCR/i)).toBeVisible();
    expect(
      screen.getByText(/^This password-protected PDF cannot be indexed\.$/i),
    ).toBeVisible();
    expect(screen.getByText(/DOCX file is corrupt/i)).toBeVisible();
    await user.click(screen.getByRole("button", { name: /retry broken\.docx/i }));

    await waitFor(() =>
      expect(api.retryDocument).toHaveBeenCalledWith("broken-docx"),
    );
  });
});
