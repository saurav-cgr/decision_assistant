// Shared document fixtures for Workspace tests. Split out so the retry-refresh
// tests (V94/V97) and the list/upload tests can share one definition instead of
// duplicating document shapes, and so each test file stays under the 500-line
// cap.

export const completedDocument = {
  id: "document-1",
  display_name: "authentication-review.md",
  media_type: "text/markdown",
  active_version_id: "version-1",
  status: "completed",
  stage: "completed",
  progress: 100,
  error: null,
  title: "Authentication Review",
  document_date: "2026-07-15",
  participants: ["Asha", "Mateo"],
  source_type: "meeting_notes",
  project: "Atlas",
  modification_state: "modified",
  decision_count: 3,
};

export function failedListItem(id: string, displayName: string) {
  return {
    ...completedDocument,
    id,
    display_name: displayName,
    status: "failed",
    error: { code: "docx_parse_failed", retryable: true },
  };
}

export function detailFixture(id: string, displayName: string, status: string) {
  const failed = status === "failed";
  return {
    id,
    display_name: displayName,
    media_type: completedDocument.media_type,
    active_version: null,
    status,
    stage: status,
    progress: failed ? 40 : 0,
    error: failed ? { code: "docx_parse_failed", retryable: true } : null,
    passages: [],
  };
}
