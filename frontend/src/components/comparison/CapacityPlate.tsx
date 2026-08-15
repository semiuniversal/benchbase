import { Stack, Text } from "@mantine/core";

export function formatContextWindow(tokens: number | null | undefined): string {
  if (tokens == null || tokens <= 0) return "—";
  if (tokens >= 1024 && tokens % 1024 === 0) {
    return `${tokens / 1024}k`;
  }
  if (tokens >= 1000) {
    const k = tokens / 1000;
    const label = Number.isInteger(k) ? String(k) : k.toFixed(1);
    return `${label}k`;
  }
  return tokens.toLocaleString();
}

export function formatVramGb(gb: number | null | undefined): string {
  if (gb == null || Number.isNaN(gb)) return "—";
  const label = Number.isInteger(gb) ? String(gb) : gb.toFixed(1);
  return `${label} GB`;
}

export function CapacityPlate({
  contextWindow,
  vramGb,
}: {
  contextWindow?: number | null;
  vramGb?: number | null;
}) {
  const ctx = formatContextWindow(contextWindow);
  const vram = formatVramGb(vramGb);
  if (ctx === "—" && vram === "—") {
    return (
      <Text size="xs" c="dimmed">
        ctx — · VRAM —
      </Text>
    );
  }
  return (
    <Stack gap={0}>
      <Text size="sm">
        ctx {ctx}
        <Text span size="xs" c="dimmed">
          {" · "}VRAM {vram}
        </Text>
      </Text>
    </Stack>
  );
}
