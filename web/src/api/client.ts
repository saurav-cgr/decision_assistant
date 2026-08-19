import type {
  ApiErrorPayload,
  AuthResponse,
  AuthenticatedUser,
  DecisionCorrectionRequest,
  DecisionDetail,
  DecisionListResponse,
  DecisionRelation,
  DecisionRelationRequest,
  DocumentListResponse,
  EvaluationRun,
  EvaluationRunRequest,
  EvaluationRunSummary,
  QuestionResponse,
  QuestionHistoryListResponse,
  RetrievalTraceResponse,
  RetryResponse,
  TimelineResponse,
  UploadBatchResponse,
  WorkspaceDetail,
  WorkspaceListResponse,
} from "./types";

const configuredOrigin = import.meta.env.VITE_API_URL || "http://localhost:8000";
const API_V1 = `${configuredOrigin.replace(/\/$/, "")}/api/v1`;

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

function projectPath(path: string): `/${string}` {
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

export function signUp(username: string, password: string): Promise<AuthResponse> {
  return apiRequest<AuthResponse>("/auth/signup", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export function login(username: string, password: string): Promise<AuthResponse> {
  return apiRequest<AuthResponse>("/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export function logout(): Promise<void> {
  return apiRequest<void>("/auth/logout", { method: "POST" });
}

export function recoverUsername(recoveryCode: string): Promise<{ username: string }> {
  return apiRequest<{ username: string }>("/auth/recover-username", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ recovery_code: recoveryCode }),
  });
}

export function resetPassword(
  username: string,
  password: string,
  recoveryCode: string,
): Promise<{ recovery_code: string }> {
  return apiRequest<{ recovery_code: string }>("/auth/reset-password", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      username,
      password,
      recovery_code: recoveryCode,
    }),
  });
}

export function listWorkspaces(): Promise<WorkspaceListResponse> {
  return apiRequest<WorkspaceListResponse>("/workspaces");
}

export function createWorkspace(name: string): Promise<WorkspaceDetail> {
  return apiRequest<WorkspaceDetail>("/workspaces", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function activateWorkspace(workspaceId: string): Promise<WorkspaceDetail> {
  return apiRequest<WorkspaceDetail>(
    `/workspaces/${encodeURIComponent(workspaceId)}/activate`,
    { method: "POST" },
  );
}

export function renameWorkspace(
  workspaceId: string,
  name: string,
): Promise<WorkspaceDetail> {
  return apiRequest<WorkspaceDetail>(
    `/workspaces/${encodeURIComponent(workspaceId)}`,
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    },
  );
}

export function archiveWorkspace(workspaceId: string): Promise<WorkspaceDetail> {
  return apiRequest<WorkspaceDetail>(
    `/workspaces/${encodeURIComponent(workspaceId)}/archive`,
    { method: "POST" },
  );
}

export function deleteArchivedWorkspace(workspaceId: string): Promise<void> {
  return apiRequest<void>(`/workspaces/${encodeURIComponent(workspaceId)}`, {
    method: "DELETE",
  });
}

export function listDocuments(): Promise<DocumentListResponse> {
  return apiRequest<DocumentListResponse>(projectPath("/documents"));
}

export function answerQuestion(
  question: string,
  forceRefresh = false,
): Promise<QuestionResponse> {
  return apiRequest<QuestionResponse>(projectPath("/questions"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question, force_refresh: forceRefresh }),
  });
}

export function listQuestionHistory(
  query: string,
  page: number,
  pageSize: number,
): Promise<QuestionHistoryListResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (query) params.set("query", query);
  return apiRequest<QuestionHistoryListResponse>(
    projectPath(`/questions/history?${params.toString()}`),
  );
}

export function getQuestionHistoryItem(
  historyId: string,
): Promise<QuestionResponse> {
  return apiRequest<QuestionResponse>(
    projectPath(`/questions/history/${encodeURIComponent(historyId)}`),
  );
}

export function getRetrievalTrace(traceId: string): Promise<RetrievalTraceResponse> {
  return apiRequest<RetrievalTraceResponse>(
    projectPath(`/retrieval-traces/${encodeURIComponent(traceId)}`),
  );
}

export function getDecision(decisionId: string): Promise<DecisionDetail> {
  return apiRequest<DecisionDetail>(
    projectPath(`/decisions/${encodeURIComponent(decisionId)}`),
  );
}

export function listDecisions(): Promise<DecisionListResponse> {
  return apiRequest<DecisionListResponse>(projectPath("/decisions"));
}

export function correctDecision(
  decisionId: string,
  request: DecisionCorrectionRequest,
): Promise<DecisionDetail> {
  return apiRequest<DecisionDetail>(
    projectPath(`/decisions/${encodeURIComponent(decisionId)}`),
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    },
  );
}

export function createDecisionRelation(
  decisionId: string,
  request: DecisionRelationRequest,
): Promise<DecisionRelation> {
  return apiRequest<DecisionRelation>(
    projectPath(`/decisions/${encodeURIComponent(decisionId)}/relations`),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    },
  );
}

export function getTimeline(topic: string): Promise<TimelineResponse> {
  return apiRequest<TimelineResponse>(
    projectPath(`/timelines?topic=${encodeURIComponent(topic)}`),
  );
}

export function startEvaluationRun(
  request: EvaluationRunRequest,
): Promise<EvaluationRun> {
  return apiRequest<EvaluationRun>(projectPath("/evaluations/runs"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function getEvaluationRun(runId: string): Promise<EvaluationRun> {
  return apiRequest<EvaluationRun>(
    projectPath(`/evaluations/runs/${encodeURIComponent(runId)}`),
  );
}

export function listEvaluationRuns(
  limit = 10,
): Promise<EvaluationRunSummary[]> {
  return apiRequest<EvaluationRunSummary[]>(
    projectPath(`/evaluations/runs?limit=${encodeURIComponent(String(limit))}`),
  );
}

export function documentDetailUrl(documentId: string): string {
  return `${API_V1}/workspaces/${requireWorkspace()}/documents/${encodeURIComponent(documentId)}`;
}

export function retryDocument(documentId: string): Promise<RetryResponse> {
  return apiRequest<RetryResponse>(
    projectPath(`/documents/${encodeURIComponent(documentId)}/retry`),
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
    request.open(
      "POST",
      `${API_V1}/workspaces/${requireWorkspace()}/documents/upload`,
    );
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
