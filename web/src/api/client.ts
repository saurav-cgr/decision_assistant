import type { ApiErrorPayload, DocumentListResponse } from "./types";

const configuredOrigin = import.meta.env.VITE_API_URL || "http://localhost:8000";
const API_V1 = `${configuredOrigin.replace(/\/$/, "")}/api/v1`;

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
  const response = await fetch(`${API_V1}${path}`, { ...init, headers });

  if (!response.ok) {
    throw new ApiClientError(response.status, await parseApiError(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function listDocuments(): Promise<DocumentListResponse> {
  return apiRequest<DocumentListResponse>("/documents");
}

async function parseApiError(response: Response): Promise<ApiErrorPayload> {
  try {
    const payload = (await response.json()) as Partial<ApiErrorPayload>;
    if (
      typeof payload.code === "string" &&
      typeof payload.message === "string" &&
      typeof payload.request_id === "string"
    ) {
      return {
        code: payload.code,
        message: payload.message,
        request_id: payload.request_id,
        retryable: payload.retryable === true,
        details: payload.details ?? null,
      };
    }
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
