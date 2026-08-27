import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api/client";
import type { WorkspaceListResponse } from "../api/types";
import { AppShell } from "./AppShell";

vi.mock("../api/client", () => ({
  activateWorkspace: vi.fn(),
  createWorkspace: vi.fn(),
  listWorkspaces: vi.fn(),
  setActiveWorkspaceId: vi.fn(),
}));

vi.mock("../app/AuthContext", () => ({
  useAuth: () => ({
    signOut: vi.fn(),
    user: { id: "user-1", username: "tester" },
  }),
}));

function renderShell() {
  return render(
    <MemoryRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<p>Protected content</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppShell workspace bootstrap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("waits for workspace selection before mounting protected content", async () => {
    let resolveWorkspaces: (value: WorkspaceListResponse) => void = () => {};
    const pending = new Promise<WorkspaceListResponse>((resolve) => {
      resolveWorkspaces = resolve;
    });
    vi.mocked(api.listWorkspaces).mockReturnValue(pending);

    renderShell();

    expect(screen.getByRole("heading", { name: /loading your workspace/i })).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();

    resolveWorkspaces({
      items: [
        {
          id: "workspace-1",
          name: "Atlas",
          status: "active",
          is_active: true,
          document_count: 0,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    });

    await waitFor(() => expect(screen.getByText("Protected content")).toBeInTheDocument());
  });

  it("shows workspace setup when the user has no workspaces", async () => {
    vi.mocked(api.listWorkspaces).mockResolvedValue({ items: [] });

    renderShell();

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /create your first workspace/i })).toBeInTheDocument(),
    );
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });
});
