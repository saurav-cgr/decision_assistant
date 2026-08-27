import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { listWorkspaces, setActiveWorkspaceId } from "../api/client";
import { WorkspaceSelector } from "./WorkspaceSelector";
import { useAuth } from "../app/AuthContext";

const navigation = [
  { label: "Ask", to: "/", end: true },
  { label: "Workspace", to: "/workspace" },
  { label: "Timeline", to: "/timeline" },
  { label: "Evaluation", to: "/evaluation" },
  { label: "Account", to: "/account" },
] as const;

export function AppShell() {
  const { user, signOut } = useAuth();
  const [activeWorkspaceId, setWorkspace] = useState<string | null>(null);
  const [workspaceStatus, setWorkspaceStatus] = useState<"loading" | "ready" | "error">("loading");
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  const loadActiveWorkspace = useCallback(async () => {
    setWorkspaceStatus("loading");
    try {
      const response = await listWorkspaces();
      const active =
        response.items.find((item) => item.is_active) ?? response.items[0] ?? null;
      setActiveWorkspaceId(active?.id ?? null);
      setWorkspace(active?.id ?? null);
      setWorkspaceError(null);
      setWorkspaceStatus("ready");
    } catch (error) {
      setWorkspaceError(
        error instanceof Error ? error.message : "Workspaces could not be loaded.",
      );
      setWorkspaceStatus("error");
    }
  }, []);

  useEffect(() => {
    void loadActiveWorkspace();
  }, [loadActiveWorkspace]);

  const handleSwitch = (workspaceId: string) => {
    setActiveWorkspaceId(workspaceId);
    setWorkspace(workspaceId);
  };

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="Decision Assistant home">
          <span className="brand__mark" aria-hidden="true">
            DA
          </span>
          <span>
            <strong>Decision Assistant</strong>
            <small>Project memory, with evidence</small>
          </span>
        </a>
        <WorkspaceSelector
          activeWorkspaceId={activeWorkspaceId}
          onSwitch={handleSwitch}
        />
        <button className="account-button" type="button" onClick={() => void signOut()}>
          Sign out {user?.username}
        </button>
      </header>

      <nav className="primary-nav" aria-label="Primary navigation">
        {navigation.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={"end" in item ? item.end : false}
            className={({ isActive }) =>
              isActive ? "primary-nav__link is-active" : "primary-nav__link"
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="main-content">
        {workspaceStatus === "loading" && (
          <section className="workspace-bootstrap" aria-live="polite">
            <p className="eyebrow">Workspace</p>
            <h1>Loading your workspace…</h1>
          </section>
        )}
        {workspaceStatus === "error" && (
          <section className="workspace-bootstrap" role="alert">
            <p className="eyebrow">Workspace unavailable</p>
            <h1>{workspaceError ?? "Workspaces could not be loaded."}</h1>
            <button type="button" onClick={() => void loadActiveWorkspace()}>
              Try again
            </button>
          </section>
        )}
        {workspaceStatus === "ready" && activeWorkspaceId && (
          <Outlet key={activeWorkspaceId} />
        )}
        {workspaceStatus === "ready" && !activeWorkspaceId && (
          <section className="workspace-bootstrap" aria-labelledby="create-workspace-title">
            <p className="eyebrow">Workspace setup</p>
            <h1 id="create-workspace-title">Create your first workspace</h1>
            <p>Use “New workspace” above to create a workspace before asking questions or uploading sources.</p>
          </section>
        )}
      </main>

      <footer className="site-footer">
        <span>Local-first decision intelligence</span>
        <span>Sources remain authoritative</span>
      </footer>
    </div>
  );
}
