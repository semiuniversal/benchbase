const WORK_CLOCK_LINE =
  "Local work clock is benchmark time per correct answer across the quality axes (not decode tok/s).";

export function speedIndexExplain(referenceSeat?: string | null): string {
  const base = `${WORK_CLOCK_LINE} On Compare, indexed speed is shown as a percentage of the baseline model you choose in Settings (100% = that seat's work clock). The radar decode spoke uses the same baseline: its measured decode tok/s is the hub (center); other seats scale faster or slower from there.`;
  if (referenceSeat?.trim()) {
    return `${base} Current baseline: “${referenceSeat.trim()}”.`;
  }
  return `${base} Leave the baseline empty to show raw seconds per correct only; decode spoke falls back to 0–max in view.`;
}

export function speedIndexTooltip(
  referenceSeat?: string | null,
  referenceSecPerCorrect?: number | null,
): string {
  const parts = [
    WORK_CLOCK_LINE,
    referenceSeat?.trim()
      ? `Index 100% = same work clock as baseline seat “${referenceSeat.trim()}”.`
      : "Pick a baseline model in Settings to show speed as an index on Compare.",
  ];
  if (referenceSecPerCorrect != null && referenceSecPerCorrect > 0) {
    const sec =
      referenceSecPerCorrect >= 10
        ? `${referenceSecPerCorrect.toFixed(1)} s/correct`
        : `${referenceSecPerCorrect.toFixed(2)} s/correct`;
    parts.push(`Baseline sitting: ${sec}.`);
  }
  return parts.join(" ");
}