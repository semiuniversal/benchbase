import { Badge, Group, Stack, Text, Tooltip } from "@mantine/core";
import type { SpeedPlateData } from "../../api/client";
import { formatTokPerSec, formatTtft } from "./speedFormat";

function formatWorkClock(sec: number): string {
  if (sec >= 60) {
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    return `${m}m ${s}s`;
  }
  return sec >= 10 ? `${sec.toFixed(1)}s` : `${sec.toFixed(2)}s`;
}

function formatWall(seconds: number | null | undefined): string | null {
  if (seconds == null) return null;
  if (seconds >= 3600) {
    const h = Math.floor(seconds / 3600);
    const m = Math.round((seconds % 3600) / 60);
    return `${h}h ${m}m`;
  }
  if (seconds >= 60) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }
  return `${Math.round(seconds)}s`;
}

function formatSecPerCorrect(sec: number): string {
  return sec >= 10 ? `${sec.toFixed(1)} s/correct` : `${sec.toFixed(2)} s/correct`;
}

function blueRamp(t: number): string {
  const c = Math.max(0, Math.min(1, t));
  return `color-mix(in srgb, var(--mantine-color-blue-3) ${Math.round((1 - c) * 70)}%, var(--mantine-color-blue-7))`;
}

function indexColor(index: number): string {
  const t = Math.max(0, Math.min(1, (Math.max(0, Math.min(200, index)) - 50) / 100));
  return blueRamp(t);
}

function clockColor(sec: number, peerSec?: number[]): string {
  if (peerSec && peerSec.length >= 2) {
    const lo = Math.min(...peerSec);
    const hi = Math.max(...peerSec);
    if (hi > lo) {
      return blueRamp(1 - (sec - lo) / (hi - lo));
    }
  }
  return "var(--mantine-color-dimmed)";
}

function ThroughputReadout({ speed }: { speed?: SpeedPlateData | null }) {
  const tps = formatTokPerSec(speed?.output_tps);
  const ttft = formatTtft(speed?.ttft_ms);
  if (!tps && !ttft) return null;
  return (
    <Group gap="sm" wrap="nowrap">
      {tps ? (
        <Text fw={600} size="sm" style={{ lineHeight: 1.2 }}>
          {tps}
        </Text>
      ) : null}
      {ttft ? (
        <Text fw={600} size="sm" style={{ lineHeight: 1.2 }}>
          {ttft}
        </Text>
      ) : null}
    </Group>
  );
}

function ordinal(rank: number): string {
  if (rank === 1) return "1st";
  if (rank === 2) return "2nd";
  if (rank === 3) return "3rd";
  return `${rank}th`;
}

export function SpeedPlate({
  speed,
  rankInView,
  rankTied,
  peerSec,
  showThroughput = true,
}: {
  speed?: SpeedPlateData | null;
  rankInView?: number | null;
  rankTied?: boolean;
  peerSec?: number[];
  /** Nameplates show tok/s and TTFT here. The board has its own columns. */
  showThroughput?: boolean;
}) {
  const hasClock = speed?.sec_per_correct != null;
  const hasIndex = speed?.work_clock_index != null;
  const hasTps = speed?.output_tps != null;
  const hasTtft = speed?.ttft_ms != null;
  const contaminated = Boolean(speed?.invalid_reason) && !hasClock;

  if (!speed || (!hasClock && !hasTps && !hasTtft && !contaminated && !hasIndex)) {
    return (
      <Text size="sm" c="dimmed">
        —
      </Text>
    );
  }

  const think =
    speed.think_ms != null && speed.think_ms > 0
      ? `+${Math.round(speed.think_ms / 1000)} s · ${
          speed.think_tokens != null ? Math.round(speed.think_tokens) : "?"
        } think tok`
      : null;

  const clockSub = [
    formatWall(speed.suite_wall_s),
    speed.n_correct != null ? `${speed.n_correct} correct` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const tpsSub = [
    speed.prefill_tps != null ? `prefill ${speed.prefill_tps.toFixed(0)}` : null,
    think,
  ]
    .filter(Boolean)
    .join(" · ");

  const refName = speed.work_clock_reference;
  const refSec = speed.work_clock_reference_sec;
  const vsRef =
    hasIndex && refName
      ? `vs ${refName}${refSec != null ? ` · ${formatSecPerCorrect(refSec)}` : ""}`
      : null;

  const headlineColor = hasIndex
    ? indexColor(speed.work_clock_index as number)
    : hasClock
      ? clockColor(speed.sec_per_correct as number, peerSec)
      : undefined;

  return (
    <Stack gap={2}>
      {hasIndex || hasClock ? (
        <Group gap={6} align="baseline" wrap="nowrap">
          {hasIndex ? (
            <Tooltip label={vsRef || "Speed index vs Settings baseline"} withArrow>
              <Text fw={700} style={{ fontSize: "1.75rem", color: headlineColor, lineHeight: 1.1 }}>
                {speed.work_clock_index}
                <Text span size="xs" c="dimmed" ml={4}>
                  %
                </Text>
              </Text>
            </Tooltip>
          ) : (
            <Text fw={700} style={{ fontSize: "1.5rem", color: headlineColor, lineHeight: 1.1 }}>
              {formatWorkClock(speed.sec_per_correct as number)}
            </Text>
          )}
          {rankInView != null ? (
            <Badge size="xs" variant="light" color="blue">
              {ordinal(rankInView)}
              {rankTied ? " tie" : ""}
            </Badge>
          ) : null}
        </Group>
      ) : contaminated ? (
        <Text size="sm" c="dimmed">
          —
        </Text>
      ) : null}

      {clockSub ? (
        <Text size="xs" c="dimmed">
          {clockSub}
          {speed.work_clock_tier === "smoke" ? " · smoke" : ""}
        </Text>
      ) : null}

      {contaminated && speed.invalid_reason ? (
        <Text size="xs" c="dimmed">
          {speed.invalid_reason}
        </Text>
      ) : null}

      {hasIndex && hasClock ? (
        <Text size="xs" c="dimmed">
          {formatSecPerCorrect(speed.sec_per_correct as number)}
          {vsRef ? ` · ${vsRef}` : ""}
        </Text>
      ) : null}

      {showThroughput ? <ThroughputReadout speed={speed} /> : null}
      {tpsSub ? (
        <Text size="xs" c="dimmed">
          {tpsSub}
        </Text>
      ) : null}
    </Stack>
  );
}
