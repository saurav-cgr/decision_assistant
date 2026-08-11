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
