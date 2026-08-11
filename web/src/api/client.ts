import type {
  ApiErrorPayload,
  DocumentListResponse,
  QuestionResponse,
  RetrievalTraceResponse,
  RetryResponse,
  UploadBatchResponse,
} from "./types";

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

export function answerQuestion(question: string): Promise<QuestionResponse> {
  return apiRequest<QuestionResponse>("/questions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question }),
  });
}

export function getRetrievalTrace(traceId: string): Promise<RetrievalTraceResponse> {
  return apiRequest<RetrievalTraceResponse>(
    `/retrieval-traces/${encodeURIComponent(traceId)}`,
  );
}

export function documentDetailUrl(documentId: string): string {
  return `${API_V1}/documents/${encodeURIComponent(documentId)}`;
}

export function retryDocument(documentId: string): Promise<RetryResponse> {
  return apiRequest<RetryResponse>(
    `/documents/${encodeURIComponent(documentId)}/retry`,
    { method: "POST" },
  );
}

export function uploadDocuments(
  files: File[],
  onProgress: (progress: number) => void,
): Promise<UploadBatchResponse> {
  const body = new FormData();
  for (const file of files) {
    body.append("files", file);
  }

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_V1}/documents/upload`);
    request.setRequestHeader("accept", "application/json");
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    request.addEventListener("load", () => {
      const payload = parseJson(request.responseText);
      if (request.status >= 200 && request.status < 300) {
        resolve(payload as UploadBatchResponse);
        return;
      }
      reject(
        new ApiClientError(request.status, normalizeApiError(payload, request.status)),
      );
    });
    request.addEventListener("error", () => {
      reject(
        new ApiClientError(0, {
          code: "network_error",
          message: "The API could not be reached",
          request_id: "unavailable",
          retryable: true,
          details: null,
        }),
      );
    });
    request.send(body);
  });
}

async function parseApiError(response: Response): Promise<ApiErrorPayload> {
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

function parseJson(value: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

function normalizeApiError(payload: unknown, status: number): ApiErrorPayload {
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
