import { useCallback, useEffect, useState } from "react";
import {
  activateWorkspace,
  createWorkspace,
  listWorkspaces,
  setActiveWorkspaceId,
} from "../api/client";
import type { WorkspaceSummary } from "../api/types";

type WorkspaceSelectorProps = {
  activeWorkspaceId: string | null;
  onSwitch: (workspaceId: string) => void;
};

export function WorkspaceSelector({
  activeWorkspaceId,
  onSwitch,
}: WorkspaceSelectorProps) {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const response = await listWorkspaces();
      setWorkspaces(response.items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load workspaces");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const handleSwitch = async (workspaceId: string) => {
    if (workspaceId === activeWorkspaceId) {
      return;
    }
    try {
      await activateWorkspace(workspaceId);
      setActiveWorkspaceId(workspaceId);
      onSwitch(workspaceId);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to switch workspace");
    }
  };

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) {
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      const created = await createWorkspace(name);
      setNewName("");
      await reload();
      await activateWorkspace(created.id);
      setActiveWorkspaceId(created.id);
      onSwitch(created.id);
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : "Failed to create workspace",
      );
    } finally {
      setCreating(false);
    }
  };

  if (loading && workspaces.length === 0) {
    return <span className="workspace-selector">Loading workspaces…</span>;
  }

  return (
    <div className="workspace-selector" aria-label="Active project workspace">
      <label htmlFor="workspace-select">Project</label>
      <select
        id="workspace-select"
        value={activeWorkspaceId ?? ""}
        onChange={(event) => void handleSwitch(event.target.value)}
        disabled={loading}
      >
        {workspaces.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.name}
            {workspace.status === "archived" ? " (archived)" : ""}
          </option>
        ))}
      </select>
      <form
        className="workspace-selector__create"
        onSubmit={(event) => {
          event.preventDefault();
          void handleCreate();
        }}
      >
        <input
          aria-label="New workspace name"
          placeholder="New project…"
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
          disabled={creating}
        />
        <button type="submit" disabled={creating || !newName.trim()}>
          {creating ? "Creating…" : "Create"}
        </button>
      </form>
      {createError ? (
        <p className="form-error" role="alert">
          {createError}
        </p>
      ) : null}
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
