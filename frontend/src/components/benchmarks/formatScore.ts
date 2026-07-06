export function formatScore(taskName: string, score: number | null) {
  if (score === null) return "—";
  const name = taskName.toLowerCase();

  // Latency metrics (stored in ms — not tok/s).
  if (
    name.includes("output_completion") ||
    name.includes("output_ttft") ||
    name.includes("ttft") ||
    name.includes("completion")
  ) {
    return `${Math.round(score)} ms`;
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

export function shortTaskLabel(taskName: string) {
  const parts = taskName.split(":");
  const raw = parts.length > 1 ? parts.slice(1).join(":") : taskName;
  const labels: Record<string, string> = {
    output_completion32: "Time to output (32 tok)",
    output_tg32: "Output decode tok/s",
    output_ttft32: "Output TTFT",
    pp128: "Prefill tok/s (128 tok)",
    tg32: "Decode tok/s (legacy, mixed)",
  };
  return labels[raw] ?? raw;
}
