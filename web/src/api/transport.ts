/**
 * Transport half of the API client.
 *
 * Split out of `api/client.ts` (DB67): this module owns what every call needs — the base URLs, the
 * bearer token and active-workspace state, `ApiClientError`, `apiRequest`, and the error parsers.
 * `client.ts` keeps the endpoint definitions and re-exports the public names here, so an existing
 * `from "../api/client"` import keeps working either way.
 */

import type { ApiErrorPayload } from "./types";

// Exported (with `API_V1`) because the two host-level endpoints — the health probe and the
// diagnostics bundle — build their own URLs.
export const configuredOrigin = import.meta.env.VITE_API_URL || "http://localhost:8000";
export const API_V1 = `${configuredOrigin.replace(/\/$/, "")}/api/v1`;

let activeWorkspaceId: string | null = null;
let accessToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function setActiveWorkspaceId(workspaceId: string | null): void {
  activeWorkspaceId = workspaceId;
}

export function getActiveWorkspaceId(): string | null {
  return activeWorkspaceId;
}

/** The bearer token, for the callers that build their own request (the upload XHR). */
export function getAccessToken(): string | null {
  return accessToken;
}

/** Report a 401 to the shell's handler, for the callers that build their own request. */
export function handleUnauthorized(): void {
  unauthorizedHandler?.();
}

function requireWorkspace(): string {
  if (!activeWorkspaceId) {
    throw new ApiClientError(0, {
      code: "no_active_workspace",
      message: "No active workspace is selected",
      request_id: "unavailable",
      retryable: false,
      details: null,
    });
  }
  return activeWorkspaceId;
}

// Exported so feature modules can build workspace-scoped paths without re-implementing the
// active-workspace guard (see `api/provider.ts`).
export function projectPath(path: string): `/${string}` {
  return `/workspaces/${requireWorkspace()}${path}` as `/${string}`;
}

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;
  readonly retryable: boolean;
  readonly details: unknown | null;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = payload.code;
    this.requestId = payload.request_id;
    this.retryable = payload.retryable;
    this.details = payload.details;
  }
}

export async function apiRequest<T>(
  path: `/${string}`,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (accessToken) {
    headers.set("authorization", `Bearer ${accessToken}`);
  }
  const response = await fetch(`${API_V1}${path}`, { ...init, headers });

  if (!response.ok) {
    if (response.status === 401) {
      unauthorizedHandler?.();
    }
    throw new ApiClientError(response.status, await parseApiError(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function parseApiError(response: Response): Promise<ApiErrorPayload> {
  try {
    return normalizeApiError(await response.json(), response.status);
  } catch {
    // Fall through to stable client-side fallback.
  }
  return {
    code: "http_error",
    message: `Request failed with HTTP ${response.status}`,
    request_id: response.headers.get("x-request-id") ?? "unavailable",
    retryable: response.status >= 500,
    details: null,
  };
}

export function parseJson(value: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

export function normalizeApiError(payload: unknown, status: number): ApiErrorPayload {
  if (payload && typeof payload === "object") {
    const candidate = payload as Partial<ApiErrorPayload>;
    if (
      typeof candidate.code === "string" &&
      typeof candidate.message === "string" &&
      typeof candidate.request_id === "string"
    ) {
      return {
        code: candidate.code,
        message: candidate.message,
        request_id: candidate.request_id,
        retryable: candidate.retryable === true,
        details: candidate.details ?? null,
      };
    }
  }
  return {
    code: "http_error",
    message: `Request failed with HTTP ${status}`,
    request_id: "unavailable",
    retryable: status >= 500,
    details: null,
  };
}
