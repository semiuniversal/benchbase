/** Shared tok/s and TTFT labels for the compare board and nameplates. */

export function formatTokPerSec(tps: number | null | undefined): string | null {
  if (tps == null || Number.isNaN(tps)) return null;
  return `${tps.toFixed(1)} tok/s`;
}

export function formatTtft(ms: number | null | undefined): string | null {
  if (ms == null || Number.isNaN(ms)) return null;
  return `${Math.round(ms)} ms`;
}
