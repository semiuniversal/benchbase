/** Public copy for the Speed index (100% anchor). */
export const SPEED_INDEX_ANCHOR_LABEL = "DeepSeek V4 Flash 0731 on OpenRouter";

const WORK_CLOCK_LINE =
  "Local work clock is benchmark time per correct answer across the quality axes (not decode tok/s).";

export function speedIndexExplain(referenceSeat?: string | null): string {
  const base = `Speed index uses ${WORK_CLOCK_LINE} 100% is anchored to ${SPEED_INDEX_ANCHOR_LABEL}.`;
  if (referenceSeat?.trim()) {
    return `${base} The baseline seat in Settings is “${referenceSeat.trim()}”.`;
  }
  return `${base} Pick a baseline seat in Settings to show indexed values on Compare.`;
}

export function speedIndexTooltip(
  referenceSeat?: string | null,
  referenceSecPerCorrect?: number | null,
): string {
  const parts = [
    WORK_CLOCK_LINE,
    `Index 100% = same work clock as ${SPEED_INDEX_ANCHOR_LABEL}.`,
  ];
  if (referenceSeat?.trim()) {
    parts.push(`Baseline seat: ${referenceSeat.trim()}.`);
  }
  if (referenceSecPerCorrect != null && referenceSecPerCorrect > 0) {
    const sec =
      referenceSecPerCorrect >= 10
        ? `${referenceSecPerCorrect.toFixed(1)} s/correct`
        : `${referenceSecPerCorrect.toFixed(2)} s/correct`;
    parts.push(`Reference sitting: ${sec}.`);
  }
  return parts.join(" ");
}