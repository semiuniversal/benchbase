import { Stack, Text } from "@mantine/core";
import type { SpeedPlateData } from "../../api/client";

const DEFAULT_THRESHOLDS = { small: 20, large: 60 };

export function SpeedPlate({
  speed,
  thresholds = DEFAULT_THRESHOLDS,
}: {
  speed?: SpeedPlateData | null;
  thresholds?: { small: number; large: number };
}) {
  if (!speed || speed.output_tps == null) {
    return (
      <Text size="sm" c="dimmed">
        —
      </Text>
    );
  }
  const tps = speed.output_tps;
  const size =
    tps < thresholds.small ? "1rem" : tps < thresholds.large ? "1.35rem" : "1.75rem";
  // Single-hue ramp: pale → saturated blue (readable in dark/light).
  const t = Math.max(0, Math.min(1, tps / 100));
  const color = `color-mix(in srgb, var(--mantine-color-blue-3) ${Math.round((1 - t) * 70)}%, var(--mantine-color-blue-7))`;

  const think =
    speed.think_ms != null && speed.think_ms > 0
      ? `+${Math.round(speed.think_ms / 1000)} s · ${
          speed.think_tokens != null ? Math.round(speed.think_tokens) : "?"
        } think tok`
      : null;

  return (
    <Stack gap={2}>
      <Text fw={700} style={{ fontSize: size, color, lineHeight: 1.1 }}>
        {tps.toFixed(1)}
        <Text span size="xs" c="dimmed" ml={4}>
          tok/s
        </Text>
      </Text>
      <Text size="xs" c="dimmed">
        {[
          speed.prefill_tps != null ? `prefill ${speed.prefill_tps.toFixed(0)}` : null,
          speed.ttft_ms != null ? `ttft ${Math.round(speed.ttft_ms)} ms` : null,
          think,
        ]
          .filter(Boolean)
          .join(" · ")}
      </Text>
    </Stack>
  );
}
