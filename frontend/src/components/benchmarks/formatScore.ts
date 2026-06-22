export function formatScore(taskName: string, score: number | null) {
  if (score === null) return "—";
  const name = taskName.toLowerCase();
  if (name.includes("speed") || name.includes("tg") || name.includes("pp")) {
    return `${score.toFixed(1)} tok/s`;
  }
  if (name.includes("coding") || name.includes("humaneval") || name.includes("reasoning")) {
    return score <= 1 ? `${(score * 100).toFixed(1)}%` : `${score.toFixed(1)}%`;
  }
  return score.toFixed(2);
}

export function shortTaskLabel(taskName: string) {
  const parts = taskName.split(":");
  return parts.length > 1 ? parts.slice(1).join(":") : taskName;
}
