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
  status: "active" | "unreachable" | "archived" | string;
  is_active: boolean;
  color: string;
  base_model: string | null;
  quant_rank: number | null;
  supports_vision?: boolean;
  notes?: string | null;
  context_window?: number | null;
  max_output_tokens?: number | null;
  litellm_model_info?: Record<string, unknown> | null;
  last_checked: string | null;
  finalist_eligible?: boolean | null;
}

export interface ModelTierSummary {
  smoke_completed: boolean;
  standard_completed: boolean;
  thorough_completed: boolean;
  finalist_eligible: boolean;
}

export interface AgenticMetricsSnippet {
  run_id?: number | null;
  n_passed?: number | null;
  n_attempts?: number | null;
  mean_tool_calls?: number | null;
  mean_turns?: number | null;
  geo_mean_teff_vs_self?: number | null;
  display?: string | null;
  suite?: string | null;
}

export interface ModelRunSummary {
  id: number;
  status: string;
  tier?: string | null;
  suite_id: number;
  suite_name?: string | null;
  axis?: string | null;
  finalist: boolean;
  started_at?: string | null;
  completed_at?: string | null;
  display_label?: string | null;
  score?: number | null;
  n_passed?: number | null;
  n_attempts?: number | null;
  mean_tool_calls?: number | null;
  mean_turns?: number | null;
  geo_mean_teff_vs_self?: number | null;
}

export interface ModelDetail {
  model: ModelRecord;
  tiers: ModelTierSummary;
  last_agentic: AgenticMetricsSnippet | null;
  recent_runs: ModelRunSummary[];
}

export interface BenchmarkSuite {
  id: number;
  name: string;
  category: string;
  axis?: string | null;
  runner_class: string;
  suite_version?: string | null;
  content_hash?: string | null;
  scorer_status?: string | null;
}

export interface RunRecord {
  id: number;
  model_id: number;
  suite_id: number;
  status: string;
  tier?: string | null;
  run_group_id?: string | null;
  started_at: string | null;
  completed_at: string | null;
  results: RunResultSummary[];
  harness_version?: string | null;
  suite_version?: string | null;
  omp_provider?: string | null;
  omp_model?: string | null;
  display_label?: string | null;
}

export interface RunResultSummary {
  task_name: string;
  score: number | null;
  ci_low?: number | null;
  ci_high?: number | null;
  n_items?: number | null;
  metrics?: Record<string, unknown> | null;
}

export interface AgenticCurrentAttempt {
  item_id: string;
  task_id: string;
  seed: number;
  fixture?: string;
  instruction?: string;
  started_at?: number;
}

export interface AgenticAttemptSummary {
  item_id: string;
  task_id: string;
  seed: number;
  transcript_exists: boolean;
  transcript_path?: string | null;
  passed?: boolean | null;
  fixture?: string | null;
  instruction?: string | null;
  tool_calls?: number | null;
  turns?: number | null;
  wall_seconds?: number | null;
}

export interface AgenticTurn {
  kind: string;
  role?: string;
  text?: string;
  tool?: string;
  args?: unknown;
  result?: string;
  isError?: boolean;
  toolCallId?: string;
  type?: string;
  ts?: number | string | null;
}

export interface AgenticWorkspaceEntry {
  path: string;
  type: "file" | "dir";
  size?: number;
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
  litellm_api_key_set: boolean;
  database_url: string;
  theme: string;
  default_models: string[];
  benchmark_suites: string[];
  litebench_timeout_seconds: number;
  batch_sample_limit: number;
  routine_sample_limit: number;
}

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
  ci_low?: number | null;
  ci_high?: number | null;
  n_items?: number | null;
  suite_version?: string | null;
  current_suite_version?: string | null;
  scorer_status?: string | null;
  version_mismatch?: boolean;
  excluded_from_ranking?: boolean;
}

export interface SpeedPlateData {
  output_tps: number | null;
  ttft_ms: number | null;
  prefill_tps: number | null;
  think_ms: number | null;
  think_tokens: number | null;
  unit_tps?: string;
  unit_ms?: string;
}

export interface ScorecardEntry {
  model_name: string;
  model_color?: string | null;
  base_model?: string | null;
  quant_rank?: number | null;
  status?: string | null;
  is_active?: boolean;
  has_benchmark_history?: boolean;
  borda_score: number;
  overall_rank: number | null;
  overall_rank_tied?: boolean;
  overall_competitors?: number;
  dimensions: Record<string, DimensionScore>;
  speed?: SpeedPlateData;
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
  run_group_id?: string;
  tier?: string;
  axes_done?: number;
  axes_total?: number;
  current_runs?: {
    run_id: number;
    model_id: number;
    model_name: string;
    label: string;
    run_group_id?: string | null;
    tier?: string | null;
  }[];
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

export interface DiscoverDetail {
  name: string;
  status: string;
  error?: string;
}

export interface DiscoverResult {
  discovered: number;
  active: string[];
  unreachable?: string[];
  inactive?: string[];
  archived_skipped?: number;
  details?: DiscoverDetail[];
  checked_at?: string;
  failures?: Record<string, string>;
}

export type RunTier = "smoke" | "standard" | "thorough";

export const api = {
  models: {
    list: () => request<ModelRecord[]>("/models/"),
    get: (id: number) => request<ModelDetail>(`/models/${id}`),
    runs: (id: number, limit = 50) =>
      request<ModelRunSummary[]>(`/models/${id}/runs?limit=${limit}`),
    finalistEligible: () => request<ModelRecord[]>("/models/finalist-eligible"),
    discover: () => request<DiscoverResult>("/models/discover", { method: "POST" }),
    recheck: () => request<DiscoverResult>("/models/recheck", { method: "POST" }),
    delete: (id: number) => request<{ deleted: boolean }>(`/models/${id}`, { method: "DELETE" }),
    update: (
      id: number,
      data: {
        color?: string;
        base_model?: string;
        quant_rank?: number;
        status?: string;
        notes?: string;
      },
    ) =>
      request<ModelRecord>(`/models/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    archive: (id: number) =>
      request<ModelRecord>(`/models/${id}/archive`, { method: "POST" }),
    unarchive: (id: number) =>
      request<ModelRecord>(`/models/${id}/unarchive`, { method: "POST" }),
    archiveBulk: (model_ids: number[]) =>
      request<{ archived: number }>("/models/archive-bulk", {
        method: "POST",
        body: JSON.stringify({ model_ids }),
      }),
  },
  benchmarks: {
    suites: () => request<BenchmarkSuite[]>("/benchmarks/suites"),
    runs: (modelId?: number) =>
      request<RunRecord[]>(
        modelId != null ? `/benchmarks/runs?model_id=${modelId}` : "/benchmarks/runs",
      ),
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
      request<{ status?: string; run_id?: number; aborted?: boolean; deleted?: number }>(
        `/benchmarks/runs/${run_id}/cancel`,
        { method: "POST" },
      ),
    deleteRun: (run_id: number) =>
      request<{ deleted: boolean; deleted_count?: number; run_group_id?: string }>(
        `/benchmarks/runs/${run_id}`,
        { method: "DELETE" },
      ),
    deleteRunGroup: (run_group_id: string) =>
      request<{ deleted: number; run_group_id: string }>(
        `/benchmarks/run-groups/${encodeURIComponent(run_group_id)}`,
        { method: "DELETE" },
      ),
    abortRunGroup: (run_group_id: string) =>
      request<{ aborted: boolean; deleted: number; run_group_id: string }>(
        `/benchmarks/run-groups/${encodeURIComponent(run_group_id)}/abort`,
        { method: "POST" },
      ),
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
    agenticCurrent: (run_id: number) =>
      request<{ current: AgenticCurrentAttempt | null }>(
        `/benchmarks/runs/${run_id}/agentic/current`,
      ),
    agenticAttempts: (run_id: number) =>
      request<{ attempts: AgenticAttemptSummary[]; current: AgenticCurrentAttempt | null }>(
        `/benchmarks/runs/${run_id}/agentic/attempts`,
      ),
    agenticTranscript: (run_id: number, item_id: string) =>
      request<{
        item_id: string;
        task_id: string;
        seed: number;
        path: string;
        events: AgenticTurn[];
        raw_count: number;
      }>(
        `/benchmarks/runs/${run_id}/agentic/attempts/${encodeURIComponent(item_id)}/transcript`,
      ),
    agenticWorkspace: (run_id: number, item_id: string) =>
      request<{
        item_id: string;
        task_id: string;
        seed: number;
        fixture: string;
        instruction: string | null;
        tree: AgenticWorkspaceEntry[];
      }>(
        `/benchmarks/runs/${run_id}/agentic/attempts/${encodeURIComponent(item_id)}/workspace`,
      ),
    agenticWorkspaceFile: (run_id: number, item_id: string, path: string) =>
      request<{ path: string; content: string; fixture: string }>(
        `/benchmarks/runs/${run_id}/agentic/attempts/${encodeURIComponent(item_id)}/workspace/file?path=${encodeURIComponent(path)}`,
      ),
    batchStart: (
      model_id: number,
      tier: RunTier = "standard",
      smoke_override = false,
    ) =>
      request<BatchStatus>("/benchmarks/batch/start", {
        method: "POST",
        body: JSON.stringify({ model_id, tier, smoke_override }),
      }),
    batchStatus: () => request<BatchStatus>("/benchmarks/batch/status"),
    batchCancel: () =>
      request<BatchStatus>("/benchmarks/batch/cancel", { method: "POST" }),
    agenticStart: (body: {
      model_id: number;
      suite_version?: "mvp" | "headline";
      n_seeds?: number;
      task_ids?: string[];
      mock?: boolean;
      package_hash?: string;
      omp_provider?: "litellm" | "openrouter";
      omp_model?: string;
      instrument_validation?: boolean;
    }) =>
      request<{
        status: string;
        run_id: number;
        suite_version: string;
        n_seeds: number;
        concurrency: number;
        omp_provider?: string | null;
        omp_model?: string | null;
        instrument_validation?: boolean;
        display_label?: string;
      }>("/benchmarks/agentic/start", {
        method: "POST",
        body: JSON.stringify(body),
      }),
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
