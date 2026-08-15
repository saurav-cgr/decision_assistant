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
  selected_passage_metadata?: SelectedPassageMetadata[];
  rerank?: RerankTrace | null;
  timings: Record<string, number>;
  configuration: Record<string, unknown>;
  created_at: string;
};

export type SelectedPassageMetadata = {
  passage_id: string;
  document_version_id: string;
  chunking_profile: Record<string, unknown>;
  source_kind: string;
};

export type RerankTrace = {
  status: string;
  input_passage_ids: string[];
  output_passage_ids: string[];
  profile: Record<string, unknown>;
  fallback_reason: string | null;
};

export type DecisionStatus = "active" | "proposed" | "rejected" | "superseded";
export type SupportState = "supported" | "unsupported" | "needs_review";
export type DecisionFieldName =
  | "statement"
  | "effective_date"
  | "owner"
  | "status"
  | "reasons"
  | "alternatives"
  | "project"
  | "topic";

export type DecisionEvidence = {
  passage_id: string;
  field_name: string | null;
  quote: string;
  start_offset: number;
  end_offset: number;
  content_hash: string;
  support_state: SupportState;
  is_primary: boolean;
};

export type DecisionRevision = {
  id: string;
  field_name: string;
  old_value: unknown;
  new_value: unknown;
  evidence_passage_ids: string[];
  support_state: SupportState;
};

export type DecisionRelation = {
  id: string;
  source_decision_id: string;
  target_decision_id: string;
  relation_type: "supersedes" | "revises" | "relates_to";
  authority: "model_inferred" | "user_confirmed";
  confidence: "low" | "medium" | "high" | null;
  rationale: string | null;
};

export type DecisionSummary = {
  id: string;
  document_version_id: string;
  statement: string;
  effective_date: string | null;
  owner: string | null;
  status: DecisionStatus;
  reasons: string[];
  alternatives: string[];
  project: string | null;
  topic: string | null;
  extraction_confidence: number | null;
  provenance: "extracted" | "user_corrected";
  review_state: SupportState;
  user_edited: boolean;
  retired: boolean;
};

export type DecisionDetail = DecisionSummary & {
  evidence: DecisionEvidence[];
  revisions: DecisionRevision[];
  relations: DecisionRelation[];
};

export type DecisionListResponse = { items: DecisionSummary[] };

export type EvidenceSelection = {
  passage_id: string;
  start_offset: number;
  end_offset: number;
  content_hash: string;
};

export type DecisionCorrectionRequest = {
  changes: Array<{
    field_name: DecisionFieldName;
    value: unknown;
    support_state: "supported" | "unsupported";
    evidence: EvidenceSelection[];
  }>;
};

export type DecisionRelationRequest = {
  target_decision_id: string;
  relation_type: "supersedes" | "revises" | "relates_to";
  rationale: string | null;
};

export type TimelineEvidence = {
  passage_id: string;
  document_id: string;
  document_version_id: string;
  quote: string;
  start_offset: number;
  end_offset: number;
  content_hash: string;
  locator: Record<string, string | number>;
};

export type TimelineRelationship = {
  source_decision_id: string;
  target_decision_id: string;
  relation_type: "supersedes" | "revises" | "relates_to";
  label: "supersedes" | "revises" | "relates_to" | "possible_revision";
  authority: "model_inferred" | "user_confirmed";
  confidence: "low" | "medium" | "high" | null;
  rationale: string | null;
};

export type TimelineEntry = {
  decision_id: string;
  statement: string;
  effective_date: string | null;
  display_date: string | null;
  date_is_fallback: boolean;
  original_status: DecisionStatus;
  display_status: DecisionStatus;
  owner: string | null;
  project: string | null;
  topic: string | null;
  provenance: "extracted" | "user_corrected";
  evidence: TimelineEvidence[];
  relationships: TimelineRelationship[];
};

export type TimelineResponse = {
  topic: string;
  entries: TimelineEntry[];
};

export type EvaluationStrategy = "semantic" | "hybrid";

export type EvaluationRunRequest = {
  strategy: EvaluationStrategy;
  dataset_version: string;
  configuration: Record<string, unknown>;
};

export type EvaluationResult = {
  id: string;
  question_id: string;
  external_id: string;
  retrieved_ranks: {
    ids?: string[];
    document_ids?: string[];
    ranks?: Record<string, number>;
  };
  generated_output: Record<string, unknown> | null;
  citation_checks: { checks?: Array<Record<string, unknown>> };
  expected_values: Record<string, unknown>;
  actual_values: Record<string, unknown>;
  latency_ms: number | null;
  judge_prompt: string | null;
  judge_profile: Record<string, unknown> | null;
  judge_output: Record<string, unknown> | null;
  failure_reason: string | null;
};

export type EvaluationMetrics = {
  top_five_hit_rate: number;
  mean_reciprocal_rank: number;
  citation_structural_validity: number;
  citation_correctness: number;
  abstention_accuracy: number;
  facet_abstention_accuracy: number;
  answer_faithfulness: number;
  median_latency_ms: number;
  p95_latency_ms: number;
  question_failures: number;
};

export type EvaluationRun = EvaluationRunRequest & {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  completed_questions: number;
  total_questions: number;
  failure: Record<string, unknown> | null;
  generation_profile: Record<string, unknown>;
  embedding_profile: Record<string, unknown>;
  judge_profile: Record<string, unknown>;
  corpus_snapshot?: CorpusSnapshotEntry[];
  aggregate_metrics: EvaluationMetrics | null;
  started_at: string | null;
  completed_at: string | null;
  results: EvaluationResult[];
};

export type CorpusSnapshotEntry = {
  document_version_id: string;
  chunking_profile: Record<string, unknown>;
  source_kind: string;
};

export type EvaluationRunSummary = {
  id: string;
  strategy: EvaluationStrategy;
  status: "pending" | "running" | "completed" | "failed";
  completed_questions: number;
  total_questions: number;
  failure: Record<string, unknown> | null;
  dataset_version: string;
  aggregate_metrics: EvaluationMetrics | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
};

export type WorkspaceSummary = {
  id: string;
  name: string;
  status: "active" | "archived";
  is_active: boolean;
  document_count: number;
  created_at: string;
};

export type WorkspaceDetail = WorkspaceSummary & {
  embedding_profile: Record<string, unknown> | null;
};

export type WorkspaceListResponse = { items: WorkspaceSummary[] };
