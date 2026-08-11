/** Shared Finalist score formatting + T_eff glossary. */

export const TEFF_GLOSSARY =
  "T_eff = mean wall seconds ÷ P(success); seconds per resolved task. ∞ if the model never passes.";

export function formatTeff(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (!Number.isFinite(value)) return "∞";
  if (value >= 100) return `${value.toFixed(0)}s`;
  if (value >= 10) return `${value.toFixed(1)}s`;
  return `${value.toFixed(2)}s`;
}

export function formatPassRate(
  nPassed: number | null | undefined,
  nAttempts: number | null | undefined,
): string {
  if (nPassed == null || nAttempts == null || nAttempts <= 0) return "—";
  return `${nPassed}/${nAttempts}`;
}

export function formatMean(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return Number(value).toFixed(digits);
}
