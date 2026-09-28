import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { ApiClientError, getCorpusRebuild, retryCorpusRebuild } from "../api/client";
import type { CorpusRebuildStatus } from "../api/types";
import { CorpusRebuildBanner } from "./CorpusRebuildBanner";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  getCorpusRebuild: vi.fn(),
  retryCorpusRebuild: vi.fn(),
}));

const getStatus = vi.mocked(getCorpusRebuild);
const retryStatus = vi.mocked(retryCorpusRebuild);

function status(overrides: Partial<CorpusRebuildStatus> = {}): CorpusRebuildStatus {
  return {
    status: "running",
    reason: "corpus_reset_required",
    documents_total: 7,
    documents_completed: 0,
    started_at: "2026-09-26T10:00:00Z",
    finished_at: null,
    error: null,
    ...overrides,
  };
}

// A few milliseconds: the banner's cadence is configurable precisely so tests
// can observe polling without fake timers.
const FAST_POLL_MS = 5;

afterEach(() => {
  vi.clearAllMocks();
});

it("renders nothing when no rebuild has ever run (404, not a failure)", async () => {
  getStatus.mockRejectedValue(
    new ApiClientError(404, {
      code: "corpus_rebuild_not_found",
      message: "No corpus rebuild has run for this workspace",
      request_id: "test",
      retryable: false,
      details: null,
    }),
  );

  const { container } = render(<CorpusRebuildBanner pollIntervalMs={FAST_POLL_MS} />);

  await waitFor(() => expect(getStatus).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

it("shows how far a running rebuild has got", async () => {
  getStatus.mockResolvedValue(status({ status: "running", documents_completed: 2 }));

  render(<CorpusRebuildBanner pollIntervalMs={FAST_POLL_MS} />);

  expect(await screen.findByRole("status")).toHaveTextContent("2/7 documents");
});

it("stops polling and reports the final count once the rebuild completes", async () => {
  getStatus
    .mockResolvedValueOnce(status({ status: "running", documents_completed: 2 }))
    .mockResolvedValue(
      status({
        status: "completed",
        documents_completed: 7,
        finished_at: "2026-09-26T10:05:00Z",
      }),
    );

  render(<CorpusRebuildBanner pollIntervalMs={FAST_POLL_MS} />);

  expect(await screen.findByText(/rebuild complete · 7\/7 documents/i)).toBeVisible();
  // Completed is terminal: the banner must not keep asking.
  const callsAfterCompletion = getStatus.mock.calls.length;
  await new Promise((resolve) => setTimeout(resolve, FAST_POLL_MS * 4));
  expect(getStatus.mock.calls.length).toBe(callsAfterCompletion);
});

it("says it is still starting when the rebuild has not reported a total yet", async () => {
  getStatus.mockResolvedValue(
    status({ status: "pending", documents_total: 0, documents_completed: 0 }),
  );

  render(<CorpusRebuildBanner pollIntervalMs={FAST_POLL_MS} />);

  expect(await screen.findByRole("status")).toHaveTextContent(/starting/i);
});

it("surfaces a failed rebuild, explains the corpus is intact, and retries", async () => {
  const user = userEvent.setup();
  // The failed row is what the *first* poll sees; the retry restarts polling,
  // which then sees the retry's fresh `pending` row.
  getStatus
    .mockResolvedValueOnce(
      status({
        status: "failed",
        documents_total: 7,
        documents_completed: 0,
        error: { code: "provider_unavailable", document_id: "document-1" },
        finished_at: "2026-09-26T10:02:00Z",
      }),
    )
    .mockResolvedValue(status({ status: "pending", documents_total: 7 }));
  retryStatus.mockResolvedValueOnce(status({ status: "pending", documents_total: 7 }));

  render(<CorpusRebuildBanner pollIntervalMs={FAST_POLL_MS} />);

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(/rebuild failed \(provider_unavailable\)/i);
  expect(alert).toHaveTextContent(/unchanged/i);

  await user.click(screen.getByRole("button", { name: /retry rebuild/i }));

  expect(retryStatus).toHaveBeenCalledTimes(1);
  // Polling resumes after the retry, so the new run's progress appears.
  expect(await screen.findByRole("status")).toHaveTextContent(/starting/i);
});

it("reports a retry that the API refuses instead of looking successful", async () => {
  const user = userEvent.setup();
  getStatus.mockResolvedValue(
    status({ status: "failed", error: { code: "provider_unavailable" } }),
  );
  retryStatus.mockRejectedValue(
    new ApiClientError(409, {
      code: "corpus_rebuild_not_retryable",
      message: "A corpus rebuild can only be retried while the latest one is failed",
      request_id: "test",
      retryable: false,
      details: null,
    }),
  );

  render(<CorpusRebuildBanner pollIntervalMs={FAST_POLL_MS} />);

  await screen.findByRole("alert");
  await user.click(screen.getByRole("button", { name: /retry rebuild/i }));

  await waitFor(() =>
    expect(screen.getByText(/can only be retried/i)).toBeVisible(),
  );
});
