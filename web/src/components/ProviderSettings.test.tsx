/**
 * T052 (US6/FR-016): the provider switch and its pending-rebuild confirmation.
 *
 * The 409 that asks for confirmation is a control-flow signal, not an error, so the tests pin that it
 * opens the dialog with the server's own counts, that confirming resubmits with
 * `confirm_rebuild: true`, and that cancelling resubmits nothing.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { ApiClientError } from "../api/client";
import { getProviderDisclosure, switchProvider } from "../api/provider";
import { ProviderSettings } from "./ProviderSettings";

vi.mock("../api/provider", async (importOriginal) => ({
  // `providerSwitchPreview` stays real: this test is the one place it is exercised, and it is what
  // turns the 409 payload into the dialog's numbers.
  ...(await importOriginal<typeof import("../api/provider")>()),
  getProviderDisclosure: vi.fn(),
  switchProvider: vi.fn(),
  acknowledgeProviderDisclosure: vi.fn(),
}));

const readDisclosure = vi.mocked(getProviderDisclosure);
const submitSwitch = vi.mocked(switchProvider);

function needsConfirmation(documentsTotal: number): ApiClientError {
  return new ApiClientError(409, {
    code: "provider_switch_requires_rebuild",
    message: "Confirm the rebuild",
    request_id: "r1",
    retryable: false,
    details: {
      documents_total: documentsTotal,
      current_embedding_profile: { provider: "gemini", model: "text-embedding-004" },
      proposed_embedding_profile: { provider: "ollama", model: "embeddinggemma" },
    },
  });
}

afterEach(() => {
  // `resetAllMocks`, not `clearAllMocks`: a leftover `mockResolvedValueOnce` from a test that failed
  // early would otherwise be consumed by the next test's first call.
  vi.resetAllMocks();
});

it("opens the confirmation dialog with the server's document count, and only rebuilds once confirmed", async () => {
  const user = userEvent.setup();
  readDisclosure.mockResolvedValue({
    provider: "gemini",
    generation_provider: "gemini",
    embedding_provider: "gemini",
    generation_sends_document_text_remotely: true,
    embedding_sends_document_text_remotely: true,
    sends_document_text_remotely: true,
    acknowledged_at: "2026-09-26T00:00:00Z",
  });
  submitSwitch
    .mockRejectedValueOnce(needsConfirmation(12))
    .mockResolvedValueOnce({
      generation_provider: "gemini",
      embedding_provider: "ollama",
      embedding_profile_changed: true,
      documents_total: 12,
      disclosure_acknowledgement_cleared: false,
      rebuild: {
        status: "pending",
        reason: "provider_switch",
        documents_total: 0,
        documents_completed: 0,
        started_at: null,
        finished_at: null,
        error: null,
      },
    });

  render(<ProviderSettings />);

  expect(await screen.findByText("gemini", { selector: "strong" })).toBeVisible();
  await user.selectOptions(screen.getByLabelText(/embedding provider/i), "ollama");
  await user.click(screen.getByRole("button", { name: /save provider/i }));

  const dialog = await screen.findByRole("alertdialog");
  expect(dialog).toHaveTextContent(/re-ingests/i);
  expect(dialog).toHaveTextContent("12 document(s)");
  expect(dialog).toHaveTextContent("text-embedding-004");
  expect(dialog).toHaveTextContent("embeddinggemma");
  // First attempt asked without confirmation; nothing was dispatched on that call.
  expect(submitSwitch).toHaveBeenNthCalledWith(1, {
    generation_provider: "gemini",
    embedding_provider: "ollama",
    confirm_rebuild: false,
  });

  await user.click(screen.getByRole("button", { name: /switch and rebuild/i }));

  expect(submitSwitch).toHaveBeenNthCalledWith(2, {
    generation_provider: "gemini",
    embedding_provider: "ollama",
    confirm_rebuild: true,
  });
  expect(await screen.findByRole("status")).toHaveTextContent(/re-ingesting 12 document/i);
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

it("cancelling the dialog resubmits nothing", async () => {
  const user = userEvent.setup();
  readDisclosure.mockResolvedValue({
    provider: "gemini",
    generation_provider: "gemini",
    embedding_provider: "gemini",
    generation_sends_document_text_remotely: true,
    embedding_sends_document_text_remotely: true,
    sends_document_text_remotely: true,
    acknowledged_at: null,
  });
  submitSwitch.mockRejectedValue(needsConfirmation(3));

  render(<ProviderSettings />);
  await user.click(await screen.findByRole("button", { name: /save provider/i }));
  await screen.findByRole("alertdialog");

  await user.click(screen.getByRole("button", { name: /cancel/i }));

  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(submitSwitch).toHaveBeenCalledTimes(1);
});

it("reports a switch that needs no rebuild without asking for confirmation", async () => {
  const user = userEvent.setup();
  readDisclosure.mockResolvedValue({
    provider: "gemini",
    generation_provider: "gemini",
    embedding_provider: "gemini",
    generation_sends_document_text_remotely: true,
    embedding_sends_document_text_remotely: true,
    sends_document_text_remotely: true,
    acknowledged_at: null,
  });
  submitSwitch.mockResolvedValue({
    generation_provider: "gemini",
    embedding_provider: "gemini",
    embedding_profile_changed: false,
    documents_total: 4,
    disclosure_acknowledgement_cleared: false,
    rebuild: null,
  });

  render(<ProviderSettings />);
  await user.click(await screen.findByRole("button", { name: /save provider/i }));

  expect(await screen.findByRole("status")).toHaveTextContent(/no re-ingestion needed/i);
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

it("tells the operator what to do when the chosen provider is not configured (FR-026)", async () => {
  const user = userEvent.setup();
  readDisclosure.mockResolvedValue({
    provider: "gemini",
    generation_provider: "gemini",
    embedding_provider: "gemini",
    generation_sends_document_text_remotely: true,
    embedding_sends_document_text_remotely: true,
    sends_document_text_remotely: true,
    acknowledged_at: null,
  });
  submitSwitch.mockRejectedValue(
    new ApiClientError(409, {
      code: "provider_switch_not_configured",
      message: "Provider not configured",
      request_id: "r2",
      retryable: false,
      details: null,
    }),
  );

  render(<ProviderSettings />);
  await user.click(await screen.findByRole("button", { name: /save provider/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/not configured on this install/i);
  expect(screen.getByRole("alert")).toHaveTextContent(/docs\/providers\.md/);
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

it("shows every workspace's document count and warns when the switch clears the acknowledgement", async () => {
  // DB57: the provider choice is process-wide, so the dialog must not speak about only this
  // workspace. DB65: a local-to-remote switch also clears the data-handling acknowledgement.
  const user = userEvent.setup();
  readDisclosure.mockResolvedValue({
    provider: "ollama",
    generation_provider: "ollama",
    embedding_provider: "ollama",
    generation_sends_document_text_remotely: false,
    embedding_sends_document_text_remotely: false,
    sends_document_text_remotely: false,
    acknowledged_at: "2026-09-26T00:00:00Z",
  });
  submitSwitch
    .mockRejectedValueOnce(
      new ApiClientError(409, {
        code: "provider_switch_requires_rebuild",
        message: "Confirm the rebuild",
        request_id: "r3",
        retryable: false,
        details: {
          documents_total: 2,
          workspaces: [
            { id: "w1", name: "Atlas", documents_total: 2 },
            { id: "w2", name: "Second", documents_total: 5 },
          ],
          current_embedding_profile: { provider: "ollama", model: "embeddinggemma" },
          proposed_embedding_profile: { provider: "gemini", model: "text-embedding-004" },
          disclosure_acknowledgement_will_be_cleared: true,
        },
      }),
    )
    .mockResolvedValueOnce({
      generation_provider: "gemini",
      embedding_provider: "gemini",
      embedding_profile_changed: true,
      documents_total: 2,
      disclosure_acknowledgement_cleared: true,
      rebuild: {
        status: "pending",
        reason: "provider_switch",
        documents_total: 0,
        documents_completed: 0,
        started_at: null,
        finished_at: null,
        error: null,
      },
    });

  render(<ProviderSettings />);
  await user.selectOptions(screen.getByLabelText(/embedding provider/i), "gemini");
  await user.click(screen.getByRole("button", { name: /save provider/i }));

  const dialog = await screen.findByRole("alertdialog");
  expect(dialog).toHaveTextContent(/every workspace, not only this one/i);
  expect(dialog).toHaveTextContent("Atlas: 2 document(s)");
  expect(dialog).toHaveTextContent("Second: 5 document(s)");
  expect(screen.getByRole("note")).toHaveTextContent(/acknowledgement is cleared/i);

  await user.click(screen.getByRole("button", { name: /switch and rebuild/i }));

  expect(await screen.findByRole("status")).toHaveTextContent(/acknowledge again/i);
});
