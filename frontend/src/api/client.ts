import type {
  ApiError,
  ConfigOverrides,
  ConfigResponse,
  FinalizeResult,
  HistoryEntry,
  HistoryListResponse,
  JobDetail,
  JobListResponse,
  JobStatus,
  JobSummary,
  Keyword,
  KeywordCreate,
  KeywordUpdate,
  MarkerInput,
  ReopenResult,
  RescanResponse,
  ReviewItemDetail,
  ReviewItemStatus,
  ReviewListResponse,
  ReviewMarker,
} from "./types";

// In dev mode requests go through the Vite proxy; in production the
// SPA is served from the same origin as the API. ``VITE_API_BASE`` is
// available as an escape hatch for non-standard deployments.
const BASE = (import.meta.env.VITE_API_BASE ?? "") + "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  const body = text.length > 0 ? JSON.parse(text) : undefined;
  if (!response.ok) {
    const detail = body?.detail ?? body;
    const err: ApiError = {
      status: response.status,
      code: detail?.code ?? "http_error",
      message: detail?.message ?? response.statusText,
    };
    throw err;
  }
  return body as T;
}

function qs(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") {
      usp.set(k, String(v));
    }
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),

  listJobs: (params: { status?: JobStatus; limit?: number; offset?: number } = {}) =>
    request<JobListResponse>(
      `/jobs${qs({ status: params.status, limit: params.limit, offset: params.offset })}`,
    ),
  getJob: (id: number) => request<JobDetail>(`/jobs/${id}`),
  rescan: () => request<RescanResponse>("/jobs/rescan", { method: "POST" }),
  retryJob: (id: number) => request<JobSummary>(`/jobs/${id}/retry`, { method: "POST" }),
  reprocessJob: (id: number) => request<JobSummary>(`/jobs/${id}/reprocess`, { method: "POST" }),

  listHistory: (params: { limit?: number; offset?: number } = {}) =>
    request<HistoryListResponse>(`/history${qs({ limit: params.limit, offset: params.offset })}`),
  getHistoryEntry: (id: number) => request<HistoryEntry>(`/history/${id}`),

  getConfig: () => request<ConfigResponse>("/config"),
  putConfig: (body: ConfigOverrides) =>
    request<ConfigResponse>("/config", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  listKeywords: () => request<Keyword[]>("/config/keywords"),
  createKeyword: (body: KeywordCreate) =>
    request<Keyword>("/config/keywords", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateKeyword: (id: number, body: KeywordUpdate) =>
    request<Keyword>(`/config/keywords/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteKeyword: (id: number) => request<void>(`/config/keywords/${id}`, { method: "DELETE" }),

  listReview: (params: { status?: ReviewItemStatus; limit?: number; offset?: number } = {}) =>
    request<ReviewListResponse>(
      `/review${qs({ status: params.status, limit: params.limit, offset: params.offset })}`,
    ),
  getReview: (id: number) => request<ReviewItemDetail>(`/review/${id}`),
  putMarkers: (id: number, markers: MarkerInput[]) =>
    request<ReviewMarker[]>(`/review/${id}/markers`, {
      method: "PUT",
      body: JSON.stringify({ markers }),
    }),
  finalizeReview: (id: number) =>
    request<FinalizeResult>(`/review/${id}/finalize`, { method: "POST" }),
  reopenHistory: (partId: number) =>
    request<ReopenResult>(`/history/${partId}/reopen`, { method: "POST" }),
};

export type Api = typeof api;
