import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  ConfigOverrides,
  JobStatus,
  KeywordCreate,
  KeywordUpdate,
  MarkerInput,
  ReviewItemStatus,
} from "./types";

export const queryKeys = {
  jobs: (status?: JobStatus, limit?: number, offset?: number) =>
    ["jobs", { status, limit, offset }] as const,
  job: (id: number) => ["job", id] as const,
  history: (limit?: number, offset?: number) => ["history", { limit, offset }] as const,
  historyEntry: (id: number) => ["historyEntry", id] as const,
  config: ["config"] as const,
  keywords: ["keywords"] as const,
  reviewList: (status?: ReviewItemStatus) => ["review", { status }] as const,
  reviewItem: (id: number) => ["review", "item", id] as const,
};

export function useJobsList(opts: {
  status?: JobStatus;
  limit?: number;
  offset?: number;
  pollMs?: number;
}) {
  return useQuery({
    queryKey: queryKeys.jobs(opts.status, opts.limit, opts.offset),
    queryFn: () => api.listJobs({ status: opts.status, limit: opts.limit, offset: opts.offset }),
    refetchInterval: opts.pollMs ?? 5000,
  });
}

export function useJob(id: number | null, opts: { pollMs?: number } = {}) {
  return useQuery({
    queryKey: queryKeys.job(id ?? -1),
    queryFn: () => api.getJob(id as number),
    enabled: id !== null && id > 0,
    refetchInterval: opts.pollMs ?? 5000,
  });
}

export function useRescan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.rescan(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useRetryJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.retryJob(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: queryKeys.job(id) });
    },
  });
}

export function useReprocessJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.reprocessJob(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useHistory(opts: { limit?: number; offset?: number } = {}) {
  return useQuery({
    queryKey: queryKeys.history(opts.limit, opts.offset),
    queryFn: () => api.listHistory(opts),
  });
}

export function useConfig() {
  return useQuery({
    queryKey: queryKeys.config,
    queryFn: () => api.getConfig(),
  });
}

export function useUpdateConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ConfigOverrides) => api.putConfig(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.config });
    },
  });
}

export function useKeywords() {
  return useQuery({
    queryKey: queryKeys.keywords,
    queryFn: () => api.listKeywords(),
  });
}

export function useCreateKeyword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: KeywordCreate) => api.createKeyword(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.keywords }),
  });
}

export function useUpdateKeyword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; body: KeywordUpdate }) =>
      api.updateKeyword(args.id, args.body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.keywords }),
  });
}

export function useDeleteKeyword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteKeyword(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.keywords }),
  });
}

export function useReviewList(opts: { status?: ReviewItemStatus; pollMs?: number } = {}) {
  return useQuery({
    queryKey: queryKeys.reviewList(opts.status),
    queryFn: () => api.listReview({ status: opts.status, limit: 100 }),
    refetchInterval: opts.pollMs ?? 8000,
  });
}

export function useReviewItem(id: number | null) {
  return useQuery({
    queryKey: queryKeys.reviewItem(id ?? -1),
    queryFn: () => api.getReview(id as number),
    enabled: id !== null && id > 0,
  });
}

export function usePutMarkers(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (markers: MarkerInput[]) => api.putMarkers(id, markers),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.reviewItem(id) });
      qc.invalidateQueries({ queryKey: ["review"] });
    },
  });
}

export function useFinalizeReview(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.finalizeReview(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["history"] });
    },
  });
}

export function useReopenHistory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (partId: number) => api.reopenHistory(partId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["history"] });
    },
  });
}
