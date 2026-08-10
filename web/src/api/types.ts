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
  status: string | null;
  stage: string | null;
  progress: number | null;
  error: Record<string, unknown> | null;
};

export type DocumentListResponse = {
  items: DocumentListItem[];
};
