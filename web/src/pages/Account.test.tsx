import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  changePassword: vi.fn(),
  changeUsername: vi.fn(),
  getHealth: vi.fn(),
  rotateRecoveryCode: vi.fn(),
}));

vi.mock("../api/client", () => ({
  changePassword: api.changePassword,
  changeUsername: api.changeUsername,
  getHealth: api.getHealth,
  rotateRecoveryCode: api.rotateRecoveryCode,
}));

vi.mock("../app/AuthContext", () => ({
  useAuth: () => ({
    clearSession: vi.fn(),
    user: { username: "demo-user" },
  }),
}));

// T052: the settings page now hosts the provider switch, which reads the active provider on mount.
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
  switchProvider: vi.fn(),
  providerSwitchPreview: vi.fn().mockReturnValue(null),
}));

afterEach(() => {
  vi.clearAllMocks();
});

async function renderAccount() {
  const { Account } = await import("./Account");
  return render(<Account />);
}

describe("Account", () => {
  it("shows the app version once /health resolves", async () => {
    api.getHealth.mockResolvedValue({ status: "ok", version: "1.2.3" });

    await renderAccount();

    await waitFor(() => {
      expect(screen.getByText("Version 1.2.3")).toBeInTheDocument();
    });
  });

  it("shows an unavailable message when /health fails", async () => {
    api.getHealth.mockRejectedValue(new Error("network error"));

    await renderAccount();

    await waitFor(() => {
      expect(screen.getByText("Version unavailable")).toBeInTheDocument();
    });
  });
});
