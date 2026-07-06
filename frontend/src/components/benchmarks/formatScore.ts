import type { RunResultSummary } from "../../api/client";

export function formatScore(taskName: string, score: number | null) {
  if (score === null) return "—";
  const name = taskName.toLowerCase();

  // Latency metrics (stored in ms — not tok/s).
  if (
    name.includes("output_completion") ||
    name.includes("output_ttft") ||
    name.includes("think_time") ||
    name.includes("ttft") ||
    name.includes("completion")
  ) {
    return `${Math.round(score)} ms`;
  }

  if (name.includes("output_token_count") || name.includes("token_count")) {
    return `${Math.round(score)} tok`;
  }

  // Throughput metrics.
  if (
    name.includes("output_tg") ||
    name.includes(":tg") ||
    name.includes(":pp") ||
    name.includes("ctx_pp")
  ) {
    return `${score.toFixed(1)} tok/s`;
  }

  if (name.includes("coding") || name.includes("humaneval") || name.includes("reasoning")) {
    return score <= 1 ? `${(score * 100).toFixed(1)}%` : `${score.toFixed(1)}%`;
  }
  return score.toFixed(2);
}

export function sortRunResults(results: RunResultSummary[]) {
  const rank = (name: string) => {
    if (name.includes("output_tg")) return 0;
    if (name.includes("output_ttft")) return 1;
    if (name.includes("think_time")) return 2;
    if (name.includes("output_token_count")) return 3;
    if (name.includes("output_completion")) return 8;
    if (name.includes(":pp") || name.includes("ctx_pp")) return 4;
    return 5;
  };
  return [...results].sort((a, b) => rank(a.task_name) - rank(b.task_name));
}

export function shortTaskLabel(taskName: string, allResults?: RunResultSummary[]) {
  const parts = taskName.split(":");
  const raw = parts.length > 1 ? parts.slice(1).join(":") : taskName;
  const hasVisible = allResults?.some((r) => r.task_name.includes("output_tg")) ?? true;
  const tokMatch = raw.match(/(\d+)$/);
  const tokSuffix = tokMatch ? ` (${tokMatch[1]} tok)` : "";

  if (raw.startsWith("output_completion")) {
    return hasVisible
      ? `Time to last visible token${tokSuffix}`
      : "Wall clock (no visible output)";
  }
  if (raw.startsWith("output_tg")) return `Effective visible tok/s${tokSuffix}`;
  if (raw.startsWith("output_ttft")) return `Time to first visible token${tokSuffix}`;
  if (raw.startsWith("think_time")) return `Think time before visible output${tokSuffix}`;
  if (raw.startsWith("output_token_count")) return `Visible output tokens${tokSuffix}`;

  const labels: Record<string, string> = {
    pp128: "Prefill tok/s (128 tok)",
    tg32: "Decode tok/s (legacy, mixed)",
  };
  return labels[raw] ?? raw;
}
