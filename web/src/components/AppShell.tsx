import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  getActiveWorkspaceId,
  listWorkspaces,
  setActiveWorkspaceId,
} from "../api/client";
import { WorkspaceSelector } from "./WorkspaceSelector";
import { useAuth } from "../app/AuthContext";

const navigation = [
  { label: "Workspace", to: "/", end: true },
  { label: "Ask", to: "/ask" },
  { label: "Timeline", to: "/timeline" },
  { label: "Evaluation", to: "/evaluation" },
  { label: "Account", to: "/account" },
] as const;

export function AppShell() {
  const { user, signOut } = useAuth();
  const [activeWorkspaceId, setWorkspace] = useState<string | null>(
    getActiveWorkspaceId(),
  );

  useEffect(() => {
    let cancelled = false;
    async function loadActiveWorkspace() {
      try {
        const response = await listWorkspaces();
        if (cancelled) {
          return;
        }
        const active =
          response.items.find((item) => item.is_active) ?? response.items[0] ?? null;
        setActiveWorkspaceId(active?.id ?? null);
        setWorkspace(active?.id ?? null);
      } catch {
        // Leave the active workspace unset; pages surface the API error.
      }
    }
    void loadActiveWorkspace();
    return () => {
      cancelled = true;
    };
  }, []);

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
        <div className="local-status" aria-label="Environment status">
          <span aria-hidden="true" />
          Local
        </div>
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
        <Outlet key={activeWorkspaceId ?? "none"} />
      </main>

      <footer className="site-footer">
        <span>Local-first decision intelligence</span>
        <span>Sources remain authoritative</span>
      </footer>
    </div>
  );
}
