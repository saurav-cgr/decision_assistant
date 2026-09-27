import type {
  AuthResponse,
  AuthenticatedUser,
  DecisionCorrectionRequest,
  DecisionDetail,
  DecisionListResponse,
  DecisionRelation,
  DecisionRelationRequest,
  DocumentDetail,
  DocumentListResponse,
  EvaluationRun,
  EvaluationRunRequest,
  EvaluationRunSummary,
  QuestionResponse,
  ConversationDetail,
  ConversationMessage,
  ConversationSummary,
  CorpusRebuildStatus,
  QuestionHistoryListResponse,
  RetrievalTraceResponse,
  RetryResponse,
  SetupStatus,
  TimelineResponse,
  UploadBatchResponse,
  WorkspaceDetail,
  WorkspaceListResponse,
} from "./types";
import {
  API_V1,
  ApiClientError,
  apiRequest,
  configuredOrigin,
  getAccessToken,
  handleUnauthorized,
  normalizeApiError,
  parseApiError,
  parseJson,
  projectPath,
} from "./transport";

// DB67: the transport half of the client (base URLs, bearer/workspace state, `ApiClientError`,
// `apiRequest`, the error parsers) now lives in `api/transport.ts`. These re-exports keep the
// long-standing `from "../api/client"` imports in components, tests and `api/provider.ts` working —
// only the definitions moved, not the module's public surface.
export {
  ApiClientError,
  apiRequest,
  getActiveWorkspaceId,
  projectPath,
  setAccessToken,
  setActiveWorkspaceId,
  setUnauthorizedHandler,
} from "./transport";

export type HealthResponse = {
  status: string;
  version: string;
};

export async function getHealth(): Promise<HealthResponse> {
  // Unlike apiRequest, this is unauthenticated and lives outside /api/v1
  // (see api/src/decision_assistant/main.py's /health route).
  const response = await fetch(`${configuredOrigin.replace(/\/$/, "")}/health`, {
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiClientError(response.status, await parseApiError(response));
  }
  return (await response.json()) as HealthResponse;
}

export type DiagnosticsBundle = {
  blob: Blob;
  filename: string;
};

const DIAGNOSTICS_FALLBACK_FILENAME = "decision-assistant-diagnostics.zip";

export function parseAttachmentFilename(disposition: string | null): string | null {
  if (!disposition) {
    return null;
  }
  const match = /filename="?([^";]+)"?/.exec(disposition);
  return match ? match[1] : null;
}

export async function downloadDiagnosticsBundle(): Promise<DiagnosticsBundle> {
  // Deliberately not `apiRequest`: that helper always parses JSON, and this response is a zip. Same
  // origin, bearer token and 401 handling. The endpoint is host-level, so no workspace path is used.
  const headers = new Headers({ accept: "application/zip" });
  const token = getAccessToken();
  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_V1}/diagnostics/bundle`, { headers });
  if (!response.ok) {
    if (response.status === 401) {
      handleUnauthorized();
    }
    throw new ApiClientError(response.status, await parseApiError(response));
  }
  return {
    blob: await response.blob(),
    filename:
      parseAttachmentFilename(response.headers.get("content-disposition")) ??
      DIAGNOSTICS_FALLBACK_FILENAME,
  };
}

export async function signUp(username: string, password: string): Promise<AuthResponse> {
  return apiRequest<AuthResponse>("/auth/signup", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

// T044 (US5): both setup calls are deliberately unauthenticated — a fresh install has no user, which
// is the whole point of the flow. `getSetupStatus` is what lets the shell decide between the
// create-password screen and the sign-in form without first showing the wrong one.
export function getSetupStatus(): Promise<SetupStatus> {
  return apiRequest<SetupStatus>("/setup/status");
}

export function createFirstPassword(password: string): Promise<AuthResponse> {
  return apiRequest<AuthResponse>("/setup/password", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ password }),
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

export function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  return apiRequest<void>("/auth/me/password", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

export function changeUsername(
  currentPassword: string,
  username: string,
): Promise<void> {
  return apiRequest<void>("/auth/me/username", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ current_password: currentPassword, username }),
  });
}

export function rotateRecoveryCode(
  currentPassword: string,
): Promise<{ recovery_code: string }> {
  return apiRequest<{ recovery_code: string }>("/auth/me/recovery-code", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ current_password: currentPassword }),
  });
}

export function listWorkspaces(): Promise<WorkspaceListResponse> {
  return apiRequest<WorkspaceListResponse>("/workspaces");
}

// T032: the workspace's latest corpus rebuild. A workspace that has never run
// one answers 404 `corpus_rebuild_not_found` (see workspace/router.py), which
// callers should treat as "nothing to show", not as an error.
export function getCorpusRebuild(): Promise<CorpusRebuildStatus> {
  return apiRequest<CorpusRebuildStatus>(projectPath("/corpus-rebuild"));
}

// Only accepted while the latest rebuild is `failed`; anything else answers 409
// `corpus_rebuild_not_retryable`.
export function retryCorpusRebuild(): Promise<CorpusRebuildStatus> {
  return apiRequest<CorpusRebuildStatus>(projectPath("/corpus-rebuild/retry"), {
    method: "POST",
  });
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
export function getDocument(documentId: string): Promise<DocumentDetail> {
  return apiRequest<DocumentDetail>(
    projectPath(`/documents/${encodeURIComponent(documentId)}`),
  );
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

export function createConversation(question: string): Promise<ConversationDetail> {
  return apiRequest<ConversationDetail>(projectPath("/conversations"), {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question }),
  });
}

export function listConversations(): Promise<ConversationSummary[]> {
  return apiRequest<ConversationSummary[]>(projectPath("/conversations"));
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return apiRequest<ConversationDetail>(projectPath(`/conversations/${encodeURIComponent(id)}`));
}

export function appendConversationMessage(conversationId: string, question: string): Promise<ConversationMessage> {
  return apiRequest<ConversationMessage>(projectPath(`/conversations/${encodeURIComponent(conversationId)}/messages`), {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question }),
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
    // `projectPath` supplies the workspace segment and the no-active-workspace guard; building the
    // path here instead of reading the workspace state keeps that state private to `transport`.
    request.open("POST", `${API_V1}${projectPath("/documents/upload")}`);
    request.setRequestHeader("accept", "application/json");
    const token = getAccessToken();
    if (token) {
      request.setRequestHeader("authorization", `Bearer ${token}`);
    }
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
