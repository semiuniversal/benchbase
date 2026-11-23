import { Badge, Box, Divider, Group, SimpleGrid, Stack, Text, Tooltip } from "@mantine/core";
import type { SpeedPlateData } from "../../api/client";
import { formatTokPerSec, headlineDecodeTps } from "./speedFormat";

function formatFirstToken(ms: number | null | undefined): string | null {
  if (ms == null || Number.isNaN(ms)) return null;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

function formatPrefill(tps: number | null | undefined): string | null {
  if (tps == null || Number.isNaN(tps)) return null;
  return `${Math.round(tps).toLocaleString()} tok/s`;
}

type SpeedStatus = "measured" | "low_confidence" | "legacy" | "unavailable" | "empty";

function speedStatus(speed?: SpeedPlateData | null): SpeedStatus {
  if (!speed) return "empty";
  if (speed.decode_tps != null && !speed.decode_invalid_reason) {
    return speed.decode_confidence === "low" ? "low_confidence" : "measured";
  }
  if (speed.decode_invalid_reason) return "unavailable";
  if (speed.output_tps != null) return "legacy";
  return "empty";
}

const STATUS_BADGE: Record<
  SpeedStatus,
  { label: string; color: string }
> = {
  measured: { label: "Measured", color: "green" },
  low_confidence: { label: "Low confidence", color: "yellow" },
  legacy: { label: "Legacy profile", color: "yellow" },
  unavailable: { label: "Failed", color: "red" },
  empty: { label: "Not run", color: "gray" },
};

function profileCaption(speed?: SpeedPlateData | null): string {
  if (speed?.decode_tps_qualifier) {
    const method = speed.decode_tps_method ? ` · ${speed.decode_tps_method}` : "";
    return `${speed.decode_tps_qualifier}${method}`;
  }
  if (speed?.decode_tps_profile === "decode-4k-512-c1-v1") {
    return "4K→512 forced (legacy exact profile)";
  }
  return "Re-run Standard Speed for natural 4K decode tok/s.";
}

function medianCaption(speed?: SpeedPlateData | null): string | null {
  const v = speed?.decode_repetitions_valid;
  const r = speed?.decode_repetitions_requested;
  if (v != null && r != null) {
    const conf =
      speed?.decode_confidence === "low"
        ? " · low confidence — excluded from strict decode ranking"
        : "";
    return `Median of ${v} valid run${v === 1 ? "" : "s"} (${r} measured)${conf}`;
  }
  if (speed?.decode_tps != null) return "Median of measured runs";
  return null;
}

/** Large hero readout for model cards and compare radar legend. */
export function DecodeSpeedInline({ speed }: { speed?: SpeedPlateData | null }) {
  const raw = headlineDecodeTps(speed);
  const label = formatTokPerSec(raw);
  const status = speedStatus(speed);

  if (status === "empty" && !speed?.decode_invalid_reason) {
    return (
      <Text size="sm" c="dimmed">
        — tok/s
      </Text>
    );
  }

  return (
    <Tooltip
      label={
        speed?.decode_invalid_reason ??
        (raw != null
          ? `Single-user decode · ${profileCaption(speed)}`
          : "No decode measurement")
      }
      multiline
      w={280}
      disabled={!speed?.decode_invalid_reason && raw == null}
    >
      <Group gap={6} align="baseline" wrap="nowrap">
        {label ? (
          <>
            <Text fw={800} style={{ fontSize: "1.35rem", lineHeight: 1 }}>
              {raw!.toFixed(1)}
            </Text>
            <Text size="xs" c="dimmed" fw={600}>
              tok/s
            </Text>
          </>
        ) : (
          <Text size="sm" c="dimmed">
            — tok/s
          </Text>
        )}
        {status === "measured" || status === "low_confidence" ? (
          <Badge size="xs" variant="light" color={status === "low_confidence" ? "yellow" : "green"}>
            decode
          </Badge>
        ) : null}
      </Group>
    </Tooltip>
  );
}

/** Full speed readout card (model details / compare). */
export function DecodeSpeedCard({
  speed,
  compact = false,
}: {
  speed?: SpeedPlateData | null;
  compact?: boolean;
}) {
  const raw = headlineDecodeTps(speed);
  const status = speedStatus(speed);
  const badge = STATUS_BADGE[status];
  const median = medianCaption(speed);
  const prefill = formatPrefill(speed?.prefill_tps);
  const ttft = formatFirstToken(speed?.ttft_ms);
  const visible = formatTokPerSec(speed?.visible_decode_tps ?? speed?.output_tps);

  return (
    <Box
      style={{
        border: "1px solid var(--mantine-color-default-border)",
        borderRadius: "var(--mantine-radius-md)",
        padding: compact ? "var(--mantine-spacing-sm)" : "var(--mantine-spacing-md)",
        background: "var(--mantine-color-body)",
      }}
    >
      <Group justify="space-between" align="flex-start" wrap="nowrap" mb="xs">
        <Stack gap={2} style={{ minWidth: 0 }}>
          <Group gap="sm" align="baseline" wrap="nowrap">
            {raw != null ? (
              <>
                <Text
                  fw={800}
                  style={{
                    fontSize: compact ? "2rem" : "2.5rem",
                    lineHeight: 1,
                    letterSpacing: "-0.02em",
                  }}
                >
                  {raw.toFixed(1)}
                </Text>
                <Text size="sm" c="dimmed" fw={600}>
                  tok/s
                </Text>
              </>
            ) : (
              <Text fw={700} size="lg" c="dimmed">
                — tok/s
              </Text>
            )}
          </Group>
          <Text size="sm" fw={700}>
            Single-user decode speed
          </Text>
          {median ? (
            <Text size="xs" c="dimmed">
              {median}
            </Text>
          ) : speed?.decode_invalid_reason ? (
            <Text size="xs" c="dimmed">
              {speed.decode_invalid_reason}
            </Text>
          ) : null}
        </Stack>
        <Badge variant="light" color={badge.color} size={compact ? "sm" : "md"}>
          {badge.label}
        </Badge>
      </Group>

      <Divider my="sm" />

      <SimpleGrid cols={{ base: 1, xs: 3 }} spacing="sm">
        <Stack gap={2}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
            Prompt processing
          </Text>
          <Text fw={700} size="sm">
            {prefill ?? "—"}
          </Text>
        </Stack>
        <Stack gap={2}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
            First token
          </Text>
          <Text fw={700} size="sm">
            {ttft ?? "—"}
          </Text>
        </Stack>
        <Stack gap={2}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
            Visible decode
          </Text>
          <Text fw={700} size="sm">
            {visible ?? "—"}
          </Text>
        </Stack>
      </SimpleGrid>

      {!compact && speed?.decode_tps_exact != null ? (
        <Text size="xs" c="dimmed" mt="xs">
          Speed (exact): {speed.decode_tps_exact.toFixed(1)} tok/s
        </Text>
      ) : null}
      {!compact ? (
        <Text size="xs" c="dimmed" mt="md">
          {profileCaption(speed)}
        </Text>
      ) : null}
    </Box>
  );
}