/** Shared tok/s and TTFT labels for the compare board and nameplates. */

export function formatTokPerSec(tps: number | null | undefined): string | null {
  if (tps == null || Number.isNaN(tps)) return null;
  return `${tps.toFixed(1)} tok/s`;
}

/** Headline decode TPS with optional profile qualifier (Addendum A). */
export function formatDecodeHeadline(speed?: {
  decode_tps?: number | null;
  output_tps?: number | null;
  decode_tps_qualifier?: string | null;
} | null): { tps: string | null; qualifier: string | null } {
  const value = speed?.decode_tps ?? speed?.output_tps;
  return {
    tps: formatTokPerSec(value ?? null),
    qualifier: speed?.decode_tps_qualifier ?? null,
  };
}

export function headlineDecodeTps(speed?: SpeedPlateDataLike | null): number | null {
  if (speed?.decode_tps != null) return speed.decode_tps;
  if (speed?.output_tps != null) return speed.output_tps;
  return null;
}

type SpeedPlateDataLike = {
  decode_tps?: number | null;
  output_tps?: number | null;
};

export function formatTtft(ms: number | null | undefined): string | null {
  if (ms == null || Number.isNaN(ms)) return null;
  return `${Math.round(ms)} ms`;
}

/** Normalize decode tok/s to 0–100 for radar spoke (higher is better). */
export function normalizeDecodeForRadar(
  value: number | null,
  min: number,
  max: number,
): number | null {
  if (value == null || Number.isNaN(value)) return null;
  if (max <= min) return 50;
  return ((value - min) / (max - min)) * 100;
}
