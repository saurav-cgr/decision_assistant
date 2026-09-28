/**
 * T067 (FR-026): a provider failure must read as its own, actionable state — not as a generic
 * "Indexing failed" and not as the raw server string — while parser failures keep their own wording.
 */

import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { IngestionStatus } from "./IngestionStatus";

it("explains a rejected API key instead of showing the raw provider message", () => {
  render(
    <IngestionStatus
      status="failed"
      stage="failed"
      progress={100}
      error={{
        code: "provider_authentication_failed",
        message: "Model provider authentication failed",
        retryable: false,
      }}
    />,
  );

  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent(/rejected this install's API key/i);
  expect(alert).toHaveTextContent(/GEMINI_API_KEY/);
});

it("says where to look when the provider is unreachable", () => {
  render(
    <IngestionStatus
      status="failed"
      stage="failed"
      progress={100}
      error={{ code: "provider_unavailable", message: "Provider unavailable", retryable: true }}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent(/model provider is unreachable/i);
  expect(screen.getByRole("alert")).toHaveTextContent(/OLLAMA_BASE_URL/);
});

it("keeps a parser failure's own wording", () => {
  render(
    <IngestionStatus
      status="failed"
      stage="failed"
      progress={100}
      error={{ code: "pdf_parse_failed", message: "docling exploded", retryable: false }}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent(/corrupt or could not be read/i);
});

it("falls back to the server message for an unrecognised code", () => {
  render(
    <IngestionStatus
      status="failed"
      stage="failed"
      progress={100}
      error={{ code: "something_new", message: "A new failure mode", retryable: false }}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent("A new failure mode");
});
