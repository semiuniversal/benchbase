import type { ModelRecord, ScorecardEntry } from "../../api/client";

export const EXPORT_QUALITY_AXES = [
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "tool_calling",
  "instruction",
  "structured",
  "long_context",
] as const;

function csvEscape(value: string | number | boolean | null | undefined): string {
  if (value == null) return "";
  const s = String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function axisCols(axis: string): string[] {
  return [
    `${axis}_score`,
    `${axis}_ci_low`,
    `${axis}_ci_high`,
    `${axis}_rank`,
    `${axis}_borda_points`,
    `${axis}_n_items`,
    `${axis}_planned_n`,
  ];
}

export function scorecardToCsv(
  scorecard: ScorecardEntry[],
  models: ModelRecord[] = [],
): string {
  const byName = new Map(models.map((m) => [m.name, m]));
  const headers = [
    "model_name",
    "status",
    "is_active",
    "base_model",
    "best_tier",
    "context_window",
    "vram_gb",
    "notes",
    "overall_rank",
    "overall_rank_tied",
    "overall_competitors",
    "borda_score",
    ...EXPORT_QUALITY_AXES.flatMap((a) => axisCols(a)),
    "speed_index",
    "speed_index_reference",
    "sec_per_correct",
    "suite_wall_s",
    "n_correct",
    "work_clock_tier",
    "output_tps",
    "prefill_tps",
    "ttft_ms",
    "think_ms",
    "think_tokens",
    "speed_invalid_reason",
  ];

  const rows = [...scorecard].sort((a, b) => {
    const ra = a.overall_rank ?? 9999;
    const rb = b.overall_rank ?? 9999;
    if (ra !== rb) return ra - rb;
    return a.model_name.localeCompare(b.model_name, undefined, {
      sensitivity: "base",
    });
  });

  const lines = [headers.join(",")];
  for (const e of rows) {
    const model = byName.get(e.model_name);
    const sp = e.speed;
    const cells: (string | number | boolean | null | undefined)[] = [
      e.model_name,
      e.status ?? model?.status ?? "",
      e.is_active ?? model?.is_active ?? "",
      e.base_model ?? model?.base_model ?? "",
      e.best_tier ?? "",
      e.context_window ?? model?.context_window ?? "",
      e.vram_gb ?? model?.vram_gb ?? "",
      model?.notes ?? "",
      e.overall_rank,
      e.overall_rank_tied ?? false,
      e.overall_competitors,
      e.borda_score,
    ];
    for (const axis of EXPORT_QUALITY_AXES) {
      const d = e.dimensions[axis];
      cells.push(
        d?.primary,
        d?.ci_low,
        d?.ci_high,
        d?.rank,
        d?.borda_points,
        d?.n_items,
        d?.planned_n,
      );
    }
    cells.push(
      sp?.work_clock_index,
      sp?.work_clock_reference,
      sp?.sec_per_correct,
      sp?.suite_wall_s,
      sp?.n_correct,
      sp?.work_clock_tier,
      sp?.output_tps,
      sp?.prefill_tps,
      sp?.ttft_ms,
      sp?.think_ms,
      sp?.think_tokens,
      sp?.invalid_reason,
    );
    lines.push(cells.map(csvEscape).join(","));
  }
  return lines.join("\n") + "\n";
}

export function downloadScorecardCsv(
  scorecard: ScorecardEntry[],
  models: ModelRecord[] = [],
  filename?: string,
): void {
  const csv = scorecardToCsv(scorecard, models);
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, (c) =>
    c === "T" ? "_" : c === ":" ? "" : c,
  );
  const name = filename ?? `benchbase-models-${stamp}.csv`;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
