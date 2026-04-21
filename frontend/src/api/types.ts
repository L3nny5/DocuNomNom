// Types mirror the Pydantic v2 DTOs exposed at /api/v1.
// They are intentionally hand-maintained for Phase 3; once the OpenAPI
// schema stabilises this file should be regenerated from it.

export type JobStatus =
  | "pending"
  | "processing"
  | "review_required"
  | "completed"
  | "failed"
  | "cancelled";

export type AiBackend = "none" | "openai_compatible";
export type AiMode = "off" | "validate" | "refine" | "enhance";
export type OcrBackend = "ocrmypdf" | "external_api";

export interface JobSummary {
  id: number;
  file_id: number;
  file_name: string;
  status: JobStatus;
  attempt: number;
  mode: AiMode;
  pipeline_version: string;
  run_key: string;
  error_code: string | null;
  error_msg: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface JobEvent {
  id: number;
  job_id: number;
  type: string;
  ts: string;
  payload: Record<string, unknown>;
}

export interface JobDetail extends JobSummary {
  events: JobEvent[];
}

export interface JobListResponse {
  items: JobSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface RescanResponse {
  enqueued: number;
}

export interface HistoryEntry {
  part_id: number;
  job_id: number;
  file_name: string;
  output_name: string | null;
  output_path: string | null;
  decision: string;
  confidence: number;
  exported_at: string | null;
}

export interface HistoryListResponse {
  items: HistoryEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface SettingsView {
  pipeline_version: string;
  ai_backend: AiBackend;
  ai_mode: AiMode;
  ocr_backend: OcrBackend;
  ocr_languages: string[];
  splitter_keyword_weight: number;
  splitter_layout_weight: number;
  splitter_page_number_weight: number;
  splitter_auto_export_threshold: number;
  splitter_min_pages_per_part: number;
  archive_after_export: boolean;
}

export interface ConfigOverrides {
  ai_backend?: AiBackend | null;
  ai_mode?: AiMode | null;
  ocr_backend?: OcrBackend | null;
  ocr_languages?: string[] | null;
  splitter_keyword_weight?: number | null;
  splitter_layout_weight?: number | null;
  splitter_page_number_weight?: number | null;
  splitter_auto_export_threshold?: number | null;
  splitter_min_pages_per_part?: number | null;
  archive_after_export?: boolean | null;
}

export interface ConfigResponse {
  settings: SettingsView;
  overrides: ConfigOverrides;
  overrides_hash: string;
}

export interface Keyword {
  id: number;
  term: string;
  locale: string;
  enabled: boolean;
  weight: number;
}

export interface KeywordCreate {
  term: string;
  locale?: string;
  enabled?: boolean;
  weight?: number;
}

export interface KeywordUpdate {
  term: string;
  locale: string;
  enabled: boolean;
  weight: number;
}

export interface ApiError {
  status: number;
  code: string;
  message: string;
}

export type ReviewItemStatus = "open" | "in_progress" | "done";
export type ReviewMarkerKind = "start" | "reject_split";
export type DocumentPartDecision = "auto_export" | "review_required" | "user_confirmed";

export interface ReviewItemSummary {
  id: number;
  part_id: number;
  status: ReviewItemStatus;
  job_id: number;
  analysis_id: number;
  file_id: number;
  file_name: string;
  start_page: number;
  end_page: number;
  confidence: number;
  decision: DocumentPartDecision;
  page_count: number;
  finished_at: string | null;
}

export interface ReviewMarker {
  id: number;
  page_no: number;
  kind: ReviewMarkerKind;
  ts: string | null;
}

export interface SplitProposalView {
  id: number;
  source: string;
  start_page: number;
  end_page: number;
  confidence: number;
  reason_code: string;
}

export interface ReviewItemDetail {
  item: ReviewItemSummary;
  markers: ReviewMarker[];
  proposals: SplitProposalView[];
  pdf_url: string;
}

export interface ReviewListResponse {
  items: ReviewItemSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface MarkerInput {
  page_no: number;
  kind?: ReviewMarkerKind;
}

export interface FinalizeResult {
  item_id: number;
  job_id: number;
  job_status: JobStatus;
  exported_part_ids: number[];
  derived_count: number;
}

export interface ReopenResult {
  review_item_id: number;
  part_id: number;
  job_id: number;
}
