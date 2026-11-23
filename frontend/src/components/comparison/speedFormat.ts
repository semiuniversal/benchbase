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

export type DecodeRadarExtent = {
  /** Fastest measured tok/s in view (and reference), for scaling above the hub. */
  fasterMax: number;
  /** Slowest measured tok/s in view, for scaling below the hub. */
  slowerMin: number;
};

/** Decode spoke: configured baseline decode sits at 50 (hub); faster/slower scale from there. */
export function normalizeDecodeForRadar(
  value: number | null,
  referenceTokS: number | null,
  extent: DecodeRadarExtent | null,
): number | null {
  if (value == null || Number.isNaN(value)) return null;
  if (referenceTokS != null && referenceTokS > 0 && extent != null) {
    if (Math.abs(value - referenceTokS) < 1e-9) return 50;
    if (value > referenceTokS) {
      const span = Math.max(extent.fasterMax - referenceTokS, referenceTokS * 0.05);
      return Math.min(100, 50 + (50 * (value - referenceTokS)) / span);
    }
    const span = Math.max(referenceTokS - extent.slowerMin, referenceTokS * 0.05);
    return Math.max(0, 50 - (50 * (referenceTokS - value)) / span);
  }
  const max = extent?.fasterMax ?? 0;
  if (max <= 0) return null;
  return Math.min(100, (value / max) * 100);
}
