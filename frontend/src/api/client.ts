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
  litellm_api_key: string;
  database_url: string;
  theme: string;
  default_models: string[];
  benchmark_suites: string[];
}

export interface DimensionScore {
  rank: number | null;
  primary: number | null;
  unit: string;
  details: Record<string, number>;
}

export interface ScorecardEntry {
  model_name: string;
  composite_rank: number | null;
  dimensions: Record<string, DimensionScore>;
}

export interface DiscoverResult {
  discovered: number;
  active: string[];
  inactive: string[];
}

export const api = {
  models: {
    list: () => request<ModelRecord[]>("/models/"),
    discover: () => request<DiscoverResult>("/models/discover", { method: "POST" }),
    recheck: () => request<DiscoverResult>("/models/recheck", { method: "POST" }),
    delete: (id: number) => request<{ deleted: boolean }>(`/models/${id}`, { method: "DELETE" }),
  },
  benchmarks: {
    suites: () => request<BenchmarkSuite[]>("/benchmarks/suites"),
    runs: () => request<RunRecord[]>("/benchmarks/runs"),
    createRun: (model_id: number, suite_id: number) =>
      request<RunRecord>("/benchmarks/runs", {
        method: "POST",
        body: JSON.stringify({ model_id, suite_id }),
      }),
    startRun: (run_id: number) =>
      request<{ status: string }>(`/benchmarks/runs/${run_id}/start`, { method: "POST" }),
  },
  results: {
    byRun: (run_id: number) => request<ResultRecord[]>(`/results/by-run/${run_id}`),
    compare: (run_ids: number[]) =>
      request<unknown[]>(`/results/compare?${run_ids.map((id) => `run_ids=${id}`).join("&")}`),
    scorecard: (run_ids: number[]) =>
      request<ScorecardEntry[]>(`/results/scorecard?${run_ids.map((id) => `run_ids=${id}`).join("&")}`),
  },
  settings: {
    get: () => request<AppSettings>("/settings/"),
    update: (data: Partial<AppSettings>) =>
      request<AppSettings>("/settings/", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },
};
