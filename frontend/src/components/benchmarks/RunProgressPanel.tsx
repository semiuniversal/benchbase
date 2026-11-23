import { Progress, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api, type RunRecord } from "../../api/client";

interface RunProgressPanelProps {
  runId: number;
  active: boolean;
  runGroupId?: string | null;
  groupMembers?: RunRecord[];
  phaseLabel?: string;
}

function formatEtaLine(
  etaLabel: string | null | undefined,
  estimateLabel: string | undefined,
  kind: "axis" | "tier",
): string | null {
  if (etaLabel) {
    const cleaned = etaLabel.replace(/\s*\(this axis\)\s*/i, "").replace(/\s*\(tier\)\s*/i, "");
    if (kind === "axis") {
      return cleaned.match(/remaining/i) ? cleaned : `${cleaned} remaining`;
    }
    return cleaned;
  }
  if (estimateLabel && estimateLabel !== "—") {
    return kind === "axis" ? `Estimated axis duration: ${estimateLabel}` : `Estimated tier: ${estimateLabel}`;
  }
  return null;
}

export function RunProgressPanel({
  runId,
  active,
  runGroupId,
  groupMembers,
  phaseLabel,
}: RunProgressPanelProps) {
  const timing = useQuery({
    queryKey: ["run-timing", runId],
    queryFn: () => api.benchmarks.runTiming(runId),
    enabled: active,
    refetchInterval: active ? 1500 : false,
  });

  const batch = useQuery({
    queryKey: ["batch-status"],
    queryFn: api.benchmarks.batchStatus,
    enabled: active && Boolean(runGroupId),
    refetchInterval: active ? 2000 : false,
  });

  const tierProgress = useMemo(() => {
    const members = groupMembers ?? [];
    if (!runGroupId || members.length <= 1) return null;

    const totalAxes = members.length;
    const completedAxes = members.filter((m) => m.status === "completed").length;
    const running = members.find((m) => m.status === "running" || m.status === "pausing");
    const axisFrac =
      running?.id === runId && timing.data?.work_units_total
        ? Math.min(
            1,
            (timing.data.work_units_done || 0) / Math.max(1, timing.data.work_units_total),
          )
        : running
          ? 0
          : 0;

    const doneWeighted = completedAxes + axisFrac;
    const percent = Math.min(99, Math.max(0, (100 * doneWeighted) / totalAxes));

    const batchMatches =
      batch.data?.run_group_id && batch.data.run_group_id === runGroupId
        ? batch.data
        : null;

    const tierEta =
      formatEtaLine(
        batchMatches?.tier_eta_label ?? batchMatches?.per_model_label,
        batchMatches?.estimate_label,
        "tier",
      ) ?? null;

    return {
      percent,
      completedAxes,
      totalAxes,
      tierEta,
      label: `${completedAxes} of ${totalAxes} axes complete${axisFrac > 0 ? ` · current phase ${Math.round(axisFrac * 100)}%` : ""}`,
    };
  }, [groupMembers, runGroupId, runId, timing.data, batch.data]);

  if (!active) return null;

  const t = timing.data;
  const axisPercent =
    t?.progress_percent ??
    (t && t.work_units_total > 0
      ? Math.min(99, (100 * t.work_units_done) / t.work_units_total)
      : null);

  const axisEta = formatEtaLine(t?.eta_label, t?.estimate_label, "axis");
  const progressCaption =
    t?.progress_label ??
    (t && t.work_units_total > 0 ? `${t.work_units_done} / ${t.work_units_total} items` : null);

  const showAxis = axisPercent != null || axisEta || progressCaption;

  if (!showAxis && !tierProgress) return null;

  return (
    <Stack gap="sm" w="100%">
      {showAxis && (
        <Stack gap={4}>
          <Text size="sm" fw={600}>
            {phaseLabel ? `Current phase · ${phaseLabel}` : "Current phase"}
          </Text>
          {axisEta && (
            <Text size="sm" c="blue.7">
              Estimated {axisEta.replace(/^~/, "")}
              {t?.elapsed_label ? ` · Active ${t.elapsed_label}` : ""}
            </Text>
          )}
          {!axisEta && t?.elapsed_label ? (
            <Text size="sm" c="dimmed">
              Active {t.elapsed_label}
              {progressCaption ? ` · ${progressCaption}` : ""}
            </Text>
          ) : null}
          <Progress
            value={axisPercent ?? 0}
            size="lg"
            radius="sm"
            animated={active && (axisPercent ?? 0) < 100}
            aria-label="Current phase progress"
          />
          {progressCaption && axisEta ? (
            <Text size="xs" c="dimmed">
              {progressCaption}
              {t?.sec_per_item != null ? ` · ~${t.sec_per_item.toFixed(0)}s per item (running avg)` : ""}
            </Text>
          ) : null}
        </Stack>
      )}

      {tierProgress && (
        <Stack gap={4}>
          <Text size="sm" fw={600}>
            Whole tier set
          </Text>
          {tierProgress.tierEta ? (
            <Text size="sm" c="grape.7">
              Estimated {tierProgress.tierEta.replace(/^~/, "")}
            </Text>
          ) : (
            <Text size="xs" c="dimmed">
              {tierProgress.label}
            </Text>
          )}
          <Progress
            value={tierProgress.percent}
            size="md"
            radius="sm"
            color="grape"
            animated={active && tierProgress.percent < 100}
            aria-label="Tier set progress"
          />
          <Text size="xs" c="dimmed">
            {tierProgress.label}
          </Text>
        </Stack>
      )}
    </Stack>
  );
}