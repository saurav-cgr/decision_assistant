export type ApiErrorPayload = {
  code: string;
  message: string;
  request_id: string;
  retryable: boolean;
  details: unknown | null;
};

export type DocumentListItem = {
  id: string;
  display_name: string;
  media_type: string;
  active_version_id: string | null;
  status: "pending" | "running" | "completed" | "failed" | null;
  stage: string | null;
  progress: number | null;
  error: {
    code?: string;
    message?: string;
    retryable?: boolean;
  } | null;
  title: string | null;
  document_date: string | null;
  participants: string[];
  source_type: string | null;
  project: string | null;
  modification_state: "new" | "unchanged" | "modified" | null;
  decision_count: number;
};

export type DocumentListResponse = {
  items: DocumentListItem[];
};

export type UploadBatchResponse = {
  request_id: string;
  results: Array<{
    filename: string;
    status: "accepted" | "rejected";
    document_id: string | null;
    job_id: string | null;
    error: { code: string; message: string } | null;
  }>;
};

export type RetryResponse = {
  request_id: string;
  status: "accepted";
  document_id: string;
  job_id: string;
};

export type AnswerState = "answered" | "partial" | "conflicted" | "abstained";
export type Confidence = "high" | "medium" | "low" | "none";

export type AnswerClaim = {
  text: string;
  central: boolean;
  passage_ids: string[];
  explicit_entities: string[];
  explicit_dates: string[];
};

export type SourceCitation = {
  passage_id: string;
  quote: string;
  start_offset: number;
  end_offset: number;
  content_hash: string;
  document_id: string;
  document_name: string;
  locator: Record<string, string | number>;
};

export type EvidenceConflict = {
  facet: string;
  passage_ids: string[];
};

export type QuestionResponse = {
  answer: string;
  state: AnswerState;
  confidence: Confidence;
  claims: AnswerClaim[];
  citations: SourceCitation[];
  conflicts: EvidenceConflict[];
  unsupported_facets: string[];
  trace_id: string;
};

export type RetrievalCandidate = {
  passage_id: string;
  rank?: number;
  raw_score?: number;
  score?: number;
  fused_score?: number;
  source_ranks?: Record<string, number>;
};

export type RetrievalTraceResponse = {
  id: string;
  request_id: string;
  normalized_question: string;
  filters: Record<string, unknown>;
  semantic_candidates: RetrievalCandidate[];
  keyword_candidates: RetrievalCandidate[];
  decision_candidates: RetrievalCandidate[];
  fused_results: RetrievalCandidate[];
  selected_passage_ids: string[];
  timings: Record<string, number>;
  configuration: Record<string, unknown>;
  created_at: string;
};
