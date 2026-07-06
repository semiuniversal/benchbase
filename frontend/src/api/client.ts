const BASE = "/api";

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

export interface ModelRecord {
  id: number;
  name: string;
  endpoint_url: string;
  backend_runtime: string | null;
  quantization: string | null;
  host: string | null;
  is_active: boolean;
  color: string;
  last_checked: string | null;
}

export interface BenchmarkSuite {
  id: number;
  name: string;
  category: string;
  runner_class: string;
}

export interface RunRecord {
  id: number;
  model_id: number;
  suite_id: number;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  results: RunResultSummary[];
}

export interface RunResultSummary {
  task_name: string;
  score: number | null;
}

export interface ResultRecord {
  id: number;
  run_id: number;
  task_name: string;
  score: number | null;
  metrics: Record<string, unknown> | null;
}

export interface AppSettings {
  litellm_base_url: string;
  /** True when a key is stored server-side; the key itself is never sent to the browser. */
  litellm_api_key_set: boolean;
  database_url: string;
  theme: string;
  default_models: string[];
  benchmark_suites: string[];
  litebench_timeout_seconds: number;
  batch_sample_limit: number;
  routine_sample_limit: number;
}

/** Payload for PUT /settings — include litellm_api_key only when changing the key. */
export type SettingsUpdatePayload = Partial<
  Omit<AppSettings, "litellm_api_key_set">
> & {
  litellm_api_key?: string;
};

export interface DimensionScore {
  rank: number | null;
  rank_tied?: boolean;
  competitors?: number;
  borda_points?: number;
  primary: number | null;
  unit: string;
  details: Record<string, number>;
  sample_count?: number;
}

export interface ScorecardEntry {
  model_name: string;
  model_color?: string | null;
  is_active?: boolean;
  has_benchmark_history?: boolean;
  borda_score: number;
  overall_rank: number | null;
  overall_rank_tied?: boolean;
  overall_competitors?: number;
  dimensions: Record<string, DimensionScore>;
}

export interface BatchStatus {
  status: string;
  pending_count?: number;
  batch_id?: string;
  model_name?: string;
  total?: number;
  completed?: number;
  failed?: number;
  current_run_id?: number | null;
  current_label?: string | null;
  run_ids?: number[];
  queued_model_name?: string;
  queued_total?: number;
  estimate_label?: string;
  per_model_label?: string;
}

export interface RunTiming {
  elapsed_seconds: number;
  elapsed_label: string;
  estimate_label: string;
  eta_seconds: number | null;
  eta_label: string | null;
  progress_percent: number | null;
  progress_label: string | null;
  work_units_done: number;
  work_units_total: number;
}

export interface DurationEstimate {
  runner_class: string;
  eval_mode: string;
  work_units_total: number;
  estimate_seconds_low: number;
  estimate_seconds_high: number;
  estimate_label: string;
}

export interface DiscoverResult {
  discovered: number;
  active: string[];
  inactive: string[];
  failures?: Record<string, string>;
}

export const api = {
  models: {
    list: () => request<ModelRecord[]>("/models/"),
    discover: () => request<DiscoverResult>("/models/discover", { method: "POST" }),
    recheck: () => request<DiscoverResult>("/models/recheck", { method: "POST" }),
    delete: (id: number) => request<{ deleted: boolean }>(`/models/${id}`, { method: "DELETE" }),
    update: (id: number, data: { color: string }) =>
      request<ModelRecord>(`/models/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
  },
  benchmarks: {
    suites: () => request<BenchmarkSuite[]>("/benchmarks/suites"),
    runs: () => request<RunRecord[]>("/benchmarks/runs"),
    createRun: (
      model_id: number,
      suite_id: number,
      eval_mode: "routine" | "full" = "routine",
    ) =>
      request<RunRecord>("/benchmarks/runs", {
        method: "POST",
        body: JSON.stringify({ model_id, suite_id, eval_mode }),
      }),
    startRun: (run_id: number) =>
      request<{ status: string }>(`/benchmarks/runs/${run_id}/start`, { method: "POST" }),
    cancelRun: (run_id: number) =>
      request<{ status: string; run_id: number }>(
        `/benchmarks/runs/${run_id}/cancel`,
        { method: "POST" },
      ),
    deleteRun: (run_id: number) =>
      request<{ deleted: boolean }>(`/benchmarks/runs/${run_id}`, { method: "DELETE" }),
    deleteAllRuns: () =>
      request<{ deleted: number }>("/benchmarks/runs", { method: "DELETE" }),
    runTiming: (run_id: number) =>
      request<RunTiming>(`/benchmarks/runs/${run_id}/timing`),
    estimate: (suite_id: number, eval_mode: "routine" | "full" | "batch" = "routine") =>
      request<DurationEstimate>(
        `/benchmarks/estimate?suite_id=${suite_id}&eval_mode=${eval_mode}`,
      ),
    logHistory: (run_id: number) =>
      request<{ lines: { stream: string; text: string }[] }>(
        `/benchmarks/runs/${run_id}/log/history`,
      ),
    batchStart: (model_id: number) =>
      request<BatchStatus>("/benchmarks/batch/start", {
        method: "POST",
        body: JSON.stringify({ model_id }),
      }),
    batchStatus: () => request<BatchStatus>("/benchmarks/batch/status"),
    batchCancel: () =>
      request<BatchStatus>("/benchmarks/batch/cancel", { method: "POST" }),
  },
  results: {
    byRun: (run_id: number) => request<ResultRecord[]>(`/results/by-run/${run_id}`),
    compare: (run_ids: number[]) =>
      request<unknown[]>(`/results/compare?${run_ids.map((id) => `run_ids=${id}`).join("&")}`),
    scorecard: (run_ids: number[]) =>
      request<ScorecardEntry[]>(`/results/scorecard?${run_ids.map((id) => `run_ids=${id}`).join("&")}`),
    modelScorecard: () => request<ScorecardEntry[]>("/results/model-scorecard"),
  },
  settings: {
    get: () => request<AppSettings>("/settings/"),
    update: (data: SettingsUpdatePayload) =>
      request<AppSettings>("/settings/", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },
};
