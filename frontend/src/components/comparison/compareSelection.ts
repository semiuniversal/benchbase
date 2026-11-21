import type { ScorecardEntry } from "../../api/client";

const RADAR_AXES = [
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "tool_calling",
  "instruction",
] as const;

export type CompareDisplayFlags = {
  activeOnly: boolean;
  showSmoke: boolean;
  showUnbenchmarked: boolean;
};

/** Same rules the radar and table use to decide who is drawn. */
export function matchesCompareDisplay(
  entry: ScorecardEntry,
  flags: CompareDisplayFlags,
): boolean {
  if (flags.activeOnly && entry.is_active !== true && entry.status !== "active") {
    return false;
  }
  if (!flags.showUnbenchmarked && !entry.has_benchmark_history) {
    return false;
  }
  if (!flags.showSmoke && entry.best_tier === "smoke") {
    return false;
  }
  return true;
}

function competitionRank(
  rows: { name: string; value: number }[],
): Map<string, number> {
  const sorted = [...rows].sort((a, b) => b.value - a.value);
  const map = new Map<string, number>();
  sorted.forEach((row, i) => {
    if (i > 0 && row.value === sorted[i - 1].value) {
      map.set(row.name, map.get(sorted[i - 1].name) ?? i);
    } else {
      map.set(row.name, i + 1);
    }
  });
  return map;
}

/**
 * Best `n` models inside the current display filters.
 * Rank is recomputed on that pool, so a Smoke sitting is ignored unless
 * Include smoke results is on.
 */
export function topOverallNames(
  entries: ScorecardEntry[],
  flags: CompareDisplayFlags,
  n = 5,
): string[] {
  const pool = entries.filter((entry) => matchesCompareDisplay(entry, flags));
  const borda = new Map<string, number>();
  for (const axis of RADAR_AXES) {
    const rows: { name: string; value: number }[] = [];
    for (const entry of pool) {
      const dim = entry.dimensions[axis];
      if (!dim || dim.primary == null || dim.excluded_from_ranking) continue;
      rows.push({ name: entry.model_name, value: dim.primary });
    }
    const ranks = competitionRank(rows);
    const competitors = ranks.size;
    for (const [name, rank] of ranks) {
      borda.set(name, (borda.get(name) ?? 0) + (competitors - rank));
    }
  }
  return pool
    .filter((entry) => (borda.get(entry.model_name) ?? 0) > 0)
    .sort((a, b) => {
      const diff = (borda.get(b.model_name) ?? 0) - (borda.get(a.model_name) ?? 0);
      if (diff !== 0) return diff;
      return a.model_name.localeCompare(b.model_name, undefined, { sensitivity: "base" });
    })
    .slice(0, n)
    .map((entry) => entry.model_name);
}
