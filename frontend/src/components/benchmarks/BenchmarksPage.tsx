import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  HoverCard,
  Loader,
  Progress,
  ScrollArea,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconEye, IconListCheck, IconPlayerPause, IconPlayerPlay, IconPlayerStop, IconRefresh, IconTerminal, IconTrash } from "@tabler/icons-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type RunRecord } from "../../api/client";
import { BenchmarkRunLogModal } from "./BenchmarkRunLogModal";
import { InspectSessionModal } from "./InspectSessionModal";
import { RunTimingLine } from "./RunTimingLine";
import { ConfirmDangerDialog } from "../ConfirmDangerDialog";
import { formatScore, shortTaskLabel, sortRunResults } from "./formatScore";
import {
  formatMean,
  formatPassRate,
  formatTeff,
  TEFF_GLOSSARY,
} from "../models/agenticScoreFormat";
import {
  buildModelMaps,
  modelColor,
  ModelTag,
} from "../models/ModelColor";

const EMPTY_RUNS: RunRecord[] = [];

function statusColor(status: string) {
  switch (status) {
    case "completed": return "green";
    case "running": return "blue";
    case "pausing": return "grape";
    case "failed": return "red";
    case "cancelled": return "orange";
    case "paused": return "violet";
    case "pending": return "yellow";
    default: return "gray";
  }
}

function tierLabel(tier: string | null | undefined) {
  if (tier === "smoke") return "Smoke";
  if (tier === "thorough") return "Thorough";
  if (tier === "standard") return "Standard";
  return tier ?? "Run";
}

/** Mirror batch_scheduler._has_passing_smoke so the UI never offers a blocked tier. */
function modelHasPassingSmoke(
  runs: RunRecord[] | undefined,
  modelId: string | null,
  smokeSuiteIds: Set<number>,
): boolean {
  if (!modelId || !runs?.length || smokeSuiteIds.size === 0) return false;
  const mid = Number(modelId);
  // Prefer fully completed smoke groups.
  const byGroup = new Map<string, RunRecord[]>();
  for (const r of runs) {
    if (r.model_id !== mid || r.tier !== "smoke") continue;
    const gid = r.run_group_id ?? `solo-${r.id}`;
    if (!byGroup.has(gid)) byGroup.set(gid, []);
    byGroup.get(gid)!.push(r);
  }
  for (const members of byGroup.values()) {
    if (!members.every((m) => m.status === "completed")) continue;
    const smokeRun = members.find((m) => smokeSuiteIds.has(m.suite_id));
    if (
      smokeRun?.results?.some(
        (res) =>
          res.task_name.startsWith("smoke:") &&
          res.score != null &&
          res.score >= 60,
      )
    ) {
      return true;
    }
  }
  return false;
}

export interface RunGroupRow {
  key: string;
  run_group_id: string | null;
  model_id: number;
  tier: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  members: RunRecord[];
  current: RunRecord | null;
}

function rollupStatus(members: RunRecord[]): string {
  if (members.some((m) => m.status === "pausing")) return "pausing";
  if (members.some((m) => m.status === "running")) return "running";
  if (members.some((m) => m.status === "paused")) return "paused";
  if (members.some((m) => m.status === "pending")) return "pending";
  if (members.some((m) => m.status === "failed")) return "failed";
  if (members.some((m) => m.status === "cancelled")) return "cancelled";
  if (members.every((m) => m.status === "completed")) return "completed";
  return members[0]?.status ?? "unknown";
}

function groupRuns(runs: RunRecord[]): RunGroupRow[] {
  const groups = new Map<string, RunRecord[]>();
  const order: string[] = [];
  for (const r of runs) {
    const key = r.run_group_id ?? `solo-${r.id}`;
    if (!groups.has(key)) {
      groups.set(key, []);
      order.push(key);
    }
    groups.get(key)!.push(r);
  }
  return order.map((key) => {
    const members = (groups.get(key) ?? []).slice().sort((a, b) => a.id - b.id);
    const current =
      members.find((m) => m.status === "running" || m.status === "pausing") ??
      members.find((m) => m.status === "paused") ??
      members.find((m) => m.status === "pending") ??
      members[members.length - 1] ??
      null;
    return {
      key,
      run_group_id: members[0]?.run_group_id ?? null,
      model_id: members[0]?.model_id ?? 0,
      tier: members[0]?.tier ?? null,
      status: rollupStatus(members),
      started_at: members.map((m) => m.started_at).find(Boolean) ?? null,
      completed_at: members.every((m) => m.completed_at)
        ? members.map((m) => m.completed_at!).sort().at(-1) ?? null
        : null,
      members,
      current,
    };
  });
}

function isFinalistGroup(group: RunGroupRow): boolean {
  return group.members.some(
    (m) =>
      Boolean(m.display_label) ||
      Boolean(m.suite_version) ||
      (m.results ?? []).some((r) => String(r.task_name || "").startsWith("agentic:")),
  );
}

function axisScores(group: RunGroupRow, suiteMap: Record<number, string>) {
  const scores: { label: string; score: string; full: string }[] = [];
  for (const m of group.members) {
    const suite = suiteMap[m.suite_id] ?? `suite ${m.suite_id}`;
    const results = sortRunResults(m.results ?? []);
    if (results.length === 0) {
      const pendingLabel =
        m.display_label ||
        (m.suite_version
          ? `Finalist · ${m.suite_version}${m.harness_version ? ` · OMP ${m.harness_version}` : ""}`
          : suite);
      scores.push({
        label: shortTaskLabel(pendingLabel, []),
        score: m.status === "completed" ? "—" : m.status.slice(0, 3),
        full: `${pendingLabel}: ${m.status} (run #${m.id})`,
      });
      continue;
    }
    for (const r of results) {
      const metrics = (r.metrics ?? {}) as Record<string, unknown>;
      const label = shortTaskLabel(r.task_name, results);
      const isAgentic = String(r.task_name || "").startsWith("agentic:");
      const passBit =
        typeof metrics.n_passed === "number" && typeof metrics.n_attempts === "number"
          ? formatPassRate(metrics.n_passed, metrics.n_attempts)
          : null;
      const teffBit =
        typeof metrics.geo_mean_teff_vs_self === "number" ||
        metrics.geo_mean_teff_vs_self === null
          ? formatTeff(
              typeof metrics.geo_mean_teff_vs_self === "number"
                ? metrics.geo_mean_teff_vs_self
                : null,
            )
          : null;
      const score = isAgentic && passBit
        ? `${passBit} · T_eff ${teffBit ?? "—"}`
        : formatScore(r.task_name, r.score);
      const ci =
        r.ci_low != null && r.ci_high != null
          ? ` CI [${r.ci_low.toFixed(1)}, ${r.ci_high.toFixed(1)}]`
          : "";
      const n = r.n_items != null ? ` n=${r.n_items}` : "";
      const agenticBits: string[] = [];
      if (typeof metrics.suite === "string") agenticBits.push(`suite=${metrics.suite}`);
      if (typeof metrics.harness_version === "string") {
        agenticBits.push(`OMP ${metrics.harness_version}`);
      }
      if (passBit) agenticBits.push(`${passBit} pass`);
      if (teffBit) agenticBits.push(`T_eff ${teffBit} (vs self)`);
      if (typeof metrics.mean_tool_calls === "number") {
        agenticBits.push(`mean_tools=${formatMean(metrics.mean_tool_calls)}`);
      }
      if (typeof metrics.mean_turns === "number") {
        agenticBits.push(`mean_turns=${formatMean(metrics.mean_turns)}`);
      }
      const display =
        (typeof metrics.display === "string" && metrics.display) ||
        m.display_label ||
        null;
      const extra = agenticBits.length ? ` · ${agenticBits.join(" · ")}` : "";
      scores.push({
        label: display ? shortTaskLabel(String(display), results) : label,
        score,
        full: `${display || r.task_name}: ${score}${ci}${n}${extra} (${m.status}, run #${m.id})`,
      });
    }
  }
  return scores;
}

export function BenchmarksPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  const eligibleModels = useQuery({
    queryKey: ["finalist-eligible"],
    queryFn: api.models.finalistEligible,
  });
  const suites = useQuery({ queryKey: ["suites"], queryFn: api.benchmarks.suites });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api.benchmarks.runs(),
    refetchInterval: 5000,
  });

  const batchStatus = useQuery({
    queryKey: ["batch-status"],
    queryFn: api.benchmarks.batchStatus,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (
        data?.status === "running" ||
        data?.status === "pausing" ||
        data?.status === "paused"
      ) {
        return 2000;
      }
      if ((data?.pending_count ?? 0) > 0) return 2000;
      return false;
    },
  });

  const queueActive =
    batchStatus.data?.status === "running" ||
    batchStatus.data?.status === "pausing" ||
    batchStatus.data?.status === "paused" ||
    (batchStatus.data?.pending_count ?? 0) > 0;
  const batchRunning = batchStatus.data?.status === "running";
  const batchPausing = batchStatus.data?.status === "pausing";
  const batchPaused = batchStatus.data?.status === "paused";
  const batchLive = batchRunning || batchPausing;

  const tabParam = searchParams.get("tab") === "finalist" ? "finalist" : "tier";
  const [activeTab, setActiveTab] = useState<"tier" | "finalist">(tabParam);
  const [tierModelId, setTierModelId] = useState<string | null>(
    searchParams.get("tab") !== "finalist" ? searchParams.get("model_id") : null,
  );
  const [finalistModelId, setFinalistModelId] = useState<string | null>(
    searchParams.get("tab") === "finalist" ? searchParams.get("model_id") : null,
  );
  const [selectedTier, setSelectedTier] = useState<"smoke" | "standard" | "thorough">("smoke");
  const [smokeOverride, setSmokeOverride] = useState(false);
  const [agenticSuite, setAgenticSuite] = useState<"mvp" | "headline">("mvp");
  const [agenticInstrument, setAgenticInstrument] = useState(
    searchParams.get("instrument") === "1",
  );
  const [logGroupId, setLogGroupId] = useState<string | null>(null);
  const [logSoloRunId, setLogSoloRunId] = useState<number | null>(null);
  const [inspectRunId, setInspectRunId] = useState<number | null>(
    searchParams.get("inspect") ? Number(searchParams.get("inspect")) : null,
  );
  const [confirmAbort, setConfirmAbort] = useState<RunGroupRow | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<RunGroupRow | null>(null);

  useEffect(() => {
    setActiveTab(tabParam);
  }, [tabParam]);

  useEffect(() => {
    const mid = searchParams.get("model_id");
    if (!mid) return;
    if (tabParam === "finalist") setFinalistModelId(mid);
    else setTierModelId(mid);
  }, [searchParams, tabParam]);

  useEffect(() => {
    if (searchParams.get("instrument") === "1") setAgenticInstrument(true);
  }, [searchParams]);

  useEffect(() => {
    const inspect = searchParams.get("inspect");
    if (inspect) {
      setInspectRunId(Number(inspect));
      setActiveTab("finalist");
    }
  }, [searchParams]);

  const smokeSuiteIds = useMemo(() => {
    const ids = new Set<number>();
    for (const s of suites.data ?? []) {
      if (s.axis === "smoke") ids.add(s.id);
    }
    return ids;
  }, [suites.data]);

  const smokePassed = modelHasPassingSmoke(runs.data, tierModelId, smokeSuiteIds);
  const higherTiersUnlocked = smokePassed || smokeOverride;

  useEffect(() => {
    if (!higherTiersUnlocked && selectedTier !== "smoke") {
      setSelectedTier("smoke");
    }
  }, [higherTiersUnlocked, selectedTier]);

  useEffect(() => {
    setSmokeOverride(false);
  }, [tierModelId]);

  const archivedModelIds = useMemo(
    () =>
      new Set(
        (models.data ?? [])
          .filter((m) => m.status === "archived")
          .map((m) => m.id),
      ),
    [models.data],
  );

  const allRunGroups = useMemo(
    () => groupRuns(runs.data ?? EMPTY_RUNS),
    [runs.data],
  );
  // Hide archived-model history here; runs stay in the DB for Models / unarchive.
  const visibleRunGroups = useMemo(
    () => allRunGroups.filter((g) => !archivedModelIds.has(g.model_id)),
    [allRunGroups, archivedModelIds],
  );
  const runGroups = useMemo(
    () =>
      visibleRunGroups.filter((g) =>
        activeTab === "finalist" ? isFinalistGroup(g) : !isFinalistGroup(g),
      ),
    [visibleRunGroups, activeTab],
  );

  // Open live feed once when arriving via ?monitor=1 (banner Monitor button).
  const monitorParam = searchParams.get("monitor");
  useEffect(() => {
    if (monitorParam !== "1") return;
    if (batchStatus.isLoading || runs.isLoading) return;
    const gid =
      batchStatus.data?.run_group_id ??
      batchStatus.data?.current_runs?.[0]?.run_group_id ??
      allRunGroups.find((g) => g.status === "running" || g.status === "pausing")
        ?.run_group_id ??
      null;
    const solo =
      batchStatus.data?.current_run_id ??
      allRunGroups.find((g) => g.status === "running" || g.status === "pausing")
        ?.current?.id ??
      null;
    if (gid) setLogGroupId(gid);
    else if (solo != null) setLogSoloRunId(solo);
    const next = new URLSearchParams(searchParams);
    next.delete("monitor");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monitorParam, batchStatus.isLoading, runs.isLoading]);

  const deleteMutation = useMutation({
    mutationFn: async (group: RunGroupRow) => {
      if (group.run_group_id) {
        return api.benchmarks.deleteRunGroup(group.run_group_id);
      }
      const id = group.members[0]?.id;
      if (id == null) throw new Error("Nothing to delete");
      return api.benchmarks.deleteRun(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      notifications.show({ title: "Deleted", message: "Tier set removed.", color: "green" });
      setConfirmDelete(null);
    },
    onError: (err: Error) => {
      notifications.show({ title: "Delete failed", message: err.message, color: "red" });
    },
  });

  const abortMutation = useMutation({
    mutationFn: async (group: RunGroupRow) => {
      if (group.run_group_id) {
        return api.benchmarks.abortRunGroup(group.run_group_id);
      }
      const id = group.current?.id ?? group.members[0]?.id;
      if (id == null) throw new Error("Nothing to stop");
      return api.benchmarks.cancelRun(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["batch-status"] });
      setLogGroupId(null);
      setLogSoloRunId(null);
      setConfirmAbort(null);
      notifications.show({
        title: "Stopped and discarded",
        message: "The entire tier set was cancelled and removed.",
        color: "orange",
      });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Could not stop", message: err.message, color: "red" });
    },
  });

  const pauseMutation = useMutation({
    mutationFn: async (group: RunGroupRow) => {
      if (group.run_group_id) {
        return api.benchmarks.pauseRunGroup(group.run_group_id);
      }
      const id =
        group.current?.id ??
        group.members.find((m) => m.status === "running" || m.status === "pausing")?.id;
      if (id == null) throw new Error("Nothing to pause");
      return api.benchmarks.pauseRun(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["batch-status"] });
      notifications.show({
        title: "Pause requested",
        message: "Finishing the current item; progress is kept.",
        color: "violet",
      });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Could not pause", message: err.message, color: "red" });
    },
  });

  const resumeMutation = useMutation({
    mutationFn: async (group: RunGroupRow) => {
      if (group.run_group_id) {
        return api.benchmarks.resumeRunGroup(group.run_group_id);
      }
      const id = group.members.find((m) => m.status === "paused")?.id
        ?? group.current?.id;
      if (id == null) throw new Error("Nothing to resume");
      return api.benchmarks.resumeRun(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["batch-status"] });
      notifications.show({
        title: "Resumed",
        message: "Continuing from saved checkpoints.",
        color: "green",
      });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Could not resume", message: err.message, color: "red" });
    },
  });

  const batchMutation = useMutation({
    mutationFn: () => {
      if (!tierModelId) throw new Error("Select a model first");
      return api.benchmarks.batchStart(Number(tierModelId), selectedTier, smokeOverride);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batch-status"] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["finalist-eligible"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
      const modelName = models.data?.find((m) => String(m.id) === tierModelId)?.name;
      notifications.show({
        title: `${selectedTier} tier queued`,
        message: modelName
          ? `${selectedTier} run queued for ${modelName}. Axes execute one at a time.`
          : "Tier run queued.",
        color: "green",
      });
    },
    onError: (err: Error) => {
      notifications.show({
        title: "Could not start tier run",
        message: err.message,
        color: "red",
        autoClose: 10000,
      });
    },
  });

  const agenticMutation = useMutation({
    mutationFn: () => {
      if (!finalistModelId) throw new Error("Select a model first");
      return api.benchmarks.agenticStart({
        model_id: Number(finalistModelId),
        suite_version: agenticSuite,
        instrument_validation: agenticInstrument,
        ...(agenticInstrument
          ? {
              omp_provider: "openrouter" as const,
              omp_model: "deepseek/deepseek-v4-flash-0731",
              n_seeds: 1,
            }
          : {}),
      });
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["batch-status"] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      setLogSoloRunId(data.run_id);
      notifications.show({
        title: "Finalist · Agentic queued",
        message:
          data.display_label ||
          `Run #${data.run_id} · ${data.suite_version} · n=${data.n_seeds} · concurrency=1`,
        color: "green",
      });
    },
    onError: (err: Error) => {
      notifications.show({
        title: "Could not start agentic run",
        message: err.message,
        color: "red",
        autoClose: 10000,
      });
    },
  });

  const activeModels = models.data?.filter((m) => m.is_active || m.status === "active") ?? [];
  const tierModelOptions = activeModels.map((m) => ({
    value: String(m.id),
    label: m.name,
  }));
  const finalistPool = agenticInstrument
    ? activeModels
    : (eligibleModels.data ?? activeModels.filter((m) => m.finalist_eligible));
  const finalistModelOptions = finalistPool.map((m) => ({
    value: String(m.id),
    label: m.name,
  }));

  const modelMap = Object.fromEntries(
    (models.data ?? []).map((m) => [m.id, m.name])
  );
  const modelMaps = buildModelMaps(models.data ?? []);
  const suiteMap = Object.fromEntries(
    (suites.data ?? []).map((s) => [s.id, s.name])
  );

  if (models.isLoading || suites.isLoading) return <Loader />;

  const logGroup = logGroupId
    ? allRunGroups.find((g) => g.run_group_id === logGroupId)
    : null;
  const logSolo = logSoloRunId != null
    ? runs.data?.find((r) => r.id === logSoloRunId)
    : null;
  const inspectRun = inspectRunId != null
    ? runs.data?.find((r) => r.id === inspectRunId)
    : null;
  const batch = batchStatus.data;
  const batchProgress =
    batch?.total != null && batch.total > 0
      ? Math.round(((batch.completed ?? 0) / batch.total) * 100)
      : 0;
  const batchLiveRunId = batchLive ? batch?.current_run_id : null;
  const showRunningBanner =
    (queueActive
      || allRunGroups.some(
        (g) =>
          g.status === "running" ||
          g.status === "pausing" ||
          g.status === "paused",
      ))
    && logGroupId === null
    && logSoloRunId === null;

  const openMonitor = (group: RunGroupRow) => {
    if (group.run_group_id) setLogGroupId(group.run_group_id);
    else if (group.current) setLogSoloRunId(group.current.id);
  };

  const setTab = (value: string | null) => {
    const next = value === "finalist" ? "finalist" : "tier";
    setActiveTab(next);
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Benchmarks</Title>
        <Button
          variant="light"
          leftSection={<IconRefresh size={16} />}
          onClick={() => runs.refetch()}
        >
          Refresh
        </Button>
      </Group>

      {showRunningBanner && (
        <Card
          withBorder
          padding="sm"
          bg={
            batchPaused
              ? "var(--mantine-color-violet-light)"
              : batchPausing
                ? "var(--mantine-color-grape-light)"
                : "var(--mantine-color-blue-light)"
          }
        >
          <Stack gap="sm">
            {queueActive && (
              <>
                <Group justify="space-between">
                  <Text size="sm" fw={500}>
                    {batchPaused
                      ? `Paused${batch?.model_name ? ` — ${batch.model_name}` : ""}${
                          batch?.tier ? ` · ${tierLabel(batch.tier)}` : ""
                        } — ${batch?.axes_done ?? batch?.completed ?? 0}/${batch?.axes_total ?? batch?.total ?? "?"} (progress kept)`
                      : batchPausing
                        ? `Pausing${batch?.model_name ? ` — ${batch.model_name}` : ""}${
                            batch?.tier ? ` · ${tierLabel(batch.tier)}` : ""
                          } — finishing current item (progress kept)`
                      : batchRunning
                        ? `Running${batch?.model_name ? ` — ${batch.model_name}` : ""}${
                            batch?.tier ? ` · ${tierLabel(batch.tier)}` : ""
                          } — ${batch?.axes_done ?? batch?.completed ?? 0}/${batch?.axes_total ?? batch?.total ?? "?"}`
                        : `${batch?.pending_count ?? 0} benchmark${(batch?.pending_count ?? 0) === 1 ? "" : "s"} queued`}
                  </Text>
                  {batch?.current_label && (
                    <Text size="xs" c="dimmed">{batch.current_label}</Text>
                  )}
                </Group>
                {batch?.total != null && batch.total > 0 && (
                  <Progress value={batchProgress} size="sm" animated={batchLive} />
                )}
                {batchLiveRunId != null && (
                  <RunTimingLine runId={batchLiveRunId} active={batchLive} />
                )}
              </>
            )}
            <Group justify="flex-end">
              {batchRunning && batch?.run_group_id && (
                <Button
                  size="xs"
                  variant="light"
                  color="violet"
                  leftSection={<IconPlayerPause size={14} />}
                  loading={pauseMutation.isPending}
                  onClick={() => {
                    const g = allRunGroups.find((x) => x.run_group_id === batch.run_group_id);
                    if (g) pauseMutation.mutate(g);
                  }}
                >
                  Pause
                </Button>
              )}
              {batchPausing && (
                <Text size="xs" c="dimmed">
                  Waiting for current item to finish…
                </Text>
              )}
              {batchPaused && batch?.run_group_id && (
                <Button
                  size="xs"
                  variant="light"
                  color="green"
                  leftSection={<IconPlayerPlay size={14} />}
                  loading={resumeMutation.isPending}
                  onClick={() => {
                    const g = allRunGroups.find((x) => x.run_group_id === batch.run_group_id);
                    if (g) resumeMutation.mutate(g);
                  }}
                >
                  Resume
                </Button>
              )}
              {batch?.run_group_id && (
                <Button
                  size="xs"
                  variant="light"
                  color="red"
                  leftSection={<IconPlayerStop size={14} />}
                  loading={abortMutation.isPending}
                  onClick={() => {
                    const g = allRunGroups.find((x) => x.run_group_id === batch.run_group_id);
                    if (g) setConfirmAbort(g);
                  }}
                >
                  Stop and discard
                </Button>
              )}
              <Button
                size="xs"
                variant="light"
                leftSection={<IconTerminal size={14} />}
                onClick={() => {
                  if (batch?.run_group_id) setLogGroupId(batch.run_group_id);
                  else if (batchLiveRunId != null) setLogSoloRunId(batchLiveRunId);
                }}
              >
                View live output
              </Button>
            </Group>
          </Stack>
        </Card>
      )}

      <Tabs value={activeTab} onChange={setTab}>
        <Tabs.List>
          <Tabs.Tab value="tier">Tier runs</Tabs.Tab>
          <Tabs.Tab value="finalist">Agentic Finalist</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="tier" pt="md">
          <Card withBorder shadow="sm">
            <Stack>
              <Title order={4}>Launch a Tier Run</Title>
              <Text size="sm" c="dimmed">
                Smoke → Standard → Thorough. Manage model notes and history on the{" "}
                <Text span component={Link} to="/models" c="blue">
                  Models
                </Text>{" "}
                page. Standard unlocks Finalist for that model.
              </Text>

              {activeModels.length === 0 ? (
                <Text c="dimmed">
                  No active models. Discover them in Settings, then open Models.
                </Text>
              ) : (
                <>
                  <Select
                    label="Model"
                    placeholder="Select an active model"
                    data={tierModelOptions}
                    value={tierModelId}
                    onChange={setTierModelId}
                    searchable
                    renderOption={({ option }) => (
                      <ModelTag
                        name={option.label}
                        color={modelColor(modelMaps, { id: Number(option.value) })}
                        size="sm"
                      />
                    )}
                  />
                  {!smokePassed && tierModelId && (
                    <Checkbox
                      label="Override Smoke gate (unlocks Standard/Thorough; flagged in results)"
                      checked={smokeOverride}
                      onChange={(e) => setSmokeOverride(e.currentTarget.checked)}
                    />
                  )}
                  <Select
                    label="Tier"
                    description={
                      !tierModelId
                        ? undefined
                        : smokePassed
                          ? "This model has a passing Smoke run."
                          : smokeOverride
                            ? "Smoke gate overridden for this launch."
                            : "Run Smoke first, or check override above to unlock higher tiers."
                    }
                    data={[
                      { value: "smoke", label: "Smoke — coherency + format checks + speed" },
                      {
                        value: "standard",
                        label: "Standard — ~100 items/axis + speed",
                        disabled: !higherTiersUnlocked,
                      },
                      {
                        value: "thorough",
                        label: "Thorough — larger sets + tighter CIs",
                        disabled: !higherTiersUnlocked,
                      },
                    ]}
                    value={selectedTier}
                    onChange={(v) =>
                      setSelectedTier((v as "smoke" | "standard" | "thorough") || "smoke")
                    }
                  />
                  <Group>
                    <Button
                      leftSection={<IconListCheck size={16} />}
                      disabled={!tierModelId}
                      loading={batchMutation.isPending}
                      onClick={() => batchMutation.mutate()}
                    >
                      Run {selectedTier} tier
                    </Button>
                  </Group>
                </>
              )}
            </Stack>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="finalist" pt="md">
          <Card withBorder shadow="sm">
            <Stack>
              <Title order={4}>Finalist · Agentic</Title>
              <Text size="sm" c="dimmed">
                OMP / T_eff track. Models must have a completed Standard (or Thorough) tier
                unless Instrument validation is on.{" "}
                <Tooltip label={TEFF_GLOSSARY} multiline w={280}>
                  <Text span c="blue" style={{ cursor: "help" }}>
                    How to read T_eff
                  </Text>
                </Tooltip>
              </Text>
              {activeModels.length === 0 ? (
                <Text c="dimmed">No active models.</Text>
              ) : (
                <>
                  <Select
                    label="Model"
                    placeholder={
                      agenticInstrument
                        ? "Any active model (instrument)"
                        : "Models with completed Standard+"
                    }
                    data={finalistModelOptions}
                    value={finalistModelId}
                    onChange={setFinalistModelId}
                    searchable
                    nothingFoundMessage={
                      agenticInstrument
                        ? "No active models"
                        : "No Standard-complete models — run Standard first or enable Instrument"
                    }
                    renderOption={({ option }) => (
                      <ModelTag
                        name={option.label}
                        color={modelColor(modelMaps, { id: Number(option.value) })}
                        size="sm"
                      />
                    )}
                  />
                  <Select
                    label="Profile"
                    data={[
                      { value: "mvp", label: "MVP — 8 tasks × 3 seeds" },
                      { value: "headline", label: "Headline — ~20 tasks × 5 seeds" },
                    ]}
                    value={agenticSuite}
                    onChange={(v) => setAgenticSuite((v as "mvp" | "headline") || "mvp")}
                  />
                  <Checkbox
                    label="Instrument validation (remote agent = OpenRouter DeepSeek Flash · n=1)"
                    description="Bypasses Standard gate. Remote model is the agent under test — not a local UUT score, not a judge."
                    checked={agenticInstrument}
                    onChange={(e) => setAgenticInstrument(e.currentTarget.checked)}
                  />
                  <Group>
                    <Button
                      leftSection={<IconListCheck size={16} />}
                      disabled={!finalistModelId || queueActive}
                      loading={agenticMutation.isPending}
                      onClick={() => agenticMutation.mutate()}
                    >
                      Run Finalist · Agentic
                    </Button>
                    {queueActive && (
                      <Text size="sm" c="orange">
                        Queue busy — finish or cancel other runs first.
                      </Text>
                    )}
                  </Group>
                </>
              )}
            </Stack>
          </Card>
        </Tabs.Panel>
      </Tabs>

      <Card withBorder shadow="sm">
        <Title order={4} mb="sm">
          {activeTab === "finalist" ? "Finalist runs" : "Tier runs"}
        </Title>
        {runs.isLoading ? (
          <Loader />
        ) : runGroups.length > 0 ? (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Set</Table.Th>
                <Table.Th>Model</Table.Th>
                <Table.Th>Scores</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Started</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {runGroups.map((group) => {
                const scores = axisScores(group, suiteMap);
                return (
                  <Table.Tr key={group.key}>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {group.members.some((m) => m.display_label || m.suite_version)
                          ? "Finalist"
                          : tierLabel(group.tier)}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {group.members[0]?.display_label
                          ? group.members[0].display_label
                          : `${group.members.filter((m) => m.status === "completed").length}/${group.members.length} axes`}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <ModelTag
                        name={modelMap[group.model_id] ?? `#${group.model_id}`}
                        color={modelColor(modelMaps, { id: group.model_id })}
                      />
                    </Table.Td>
                    <Table.Td>
                      <HoverCard width={360} shadow="md" openDelay={200} position="bottom-start">
                        <HoverCard.Target>
                          <Group gap={6} wrap="wrap" style={{ maxWidth: 420, cursor: "default" }}>
                            {scores.map((s) => (
                              <Text key={s.full} size="xs" span>
                                <Text span c="dimmed">{s.label}:</Text>{" "}
                                <Text span fw={600}>{s.score}</Text>
                              </Text>
                            ))}
                          </Group>
                        </HoverCard.Target>
                        <HoverCard.Dropdown>
                          <ScrollArea.Autosize mah={280}>
                            <Stack gap={6}>
                              <Text size="sm" fw={600}>
                                {tierLabel(group.tier)} · {modelMap[group.model_id]}
                              </Text>
                              {scores.map((s) => (
                                <Text key={s.full} size="xs">{s.full}</Text>
                              ))}
                              {group.members.map((m) => (
                                <Text key={m.id} size="xs" c="dimmed">
                                  #{m.id} {suiteMap[m.suite_id] ?? m.suite_id}: {m.status}
                                </Text>
                              ))}
                            </Stack>
                          </ScrollArea.Autosize>
                        </HoverCard.Dropdown>
                      </HoverCard>
                    </Table.Td>
                    <Table.Td>
                      <Badge color={statusColor(group.status)} variant="light">
                        {group.status}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">
                        {group.started_at
                          ? new Date(group.started_at).toLocaleString()
                          : "—"}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <Tooltip label="View live / log output">
                          <ActionIcon
                            variant="subtle"
                            size="sm"
                            onClick={() => openMonitor(group)}
                            aria-label="View run log"
                          >
                            <IconTerminal size={16} />
                          </ActionIcon>
                        </Tooltip>
                        {isFinalistGroup(group) && (
                          <Tooltip label="Inspect session (workspace + transcript)">
                            <ActionIcon
                              variant="subtle"
                              size="sm"
                              onClick={() => {
                                const member =
                                  group.members.find(
                                    (m) =>
                                      m.status === "running" || m.status === "pausing",
                                  ) ??
                                  group.current ??
                                  group.members[0];
                                if (member) setInspectRunId(member.id);
                              }}
                              aria-label="Inspect session"
                            >
                              <IconEye size={16} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                        {(group.status === "running" ||
                          group.status === "pausing" ||
                          group.status === "pending") && (
                          <>
                            {group.status === "running" && (
                              <Tooltip label="Pause (keep progress)">
                                <ActionIcon
                                  variant="subtle"
                                  color="violet"
                                  size="sm"
                                  disabled={pauseMutation.isPending}
                                  onClick={() => pauseMutation.mutate(group)}
                                  aria-label="Pause"
                                >
                                  <IconPlayerPause size={16} />
                                </ActionIcon>
                              </Tooltip>
                            )}
                            {group.status === "pausing" && (
                              <Tooltip label="Finishing current item…">
                                <Badge size="sm" variant="light" color="grape">
                                  pausing
                                </Badge>
                              </Tooltip>
                            )}
                            <Tooltip label="Stop and discard this tier set">
                              <ActionIcon
                                variant="subtle"
                                color="red"
                                size="sm"
                                disabled={abortMutation.isPending}
                                onClick={() => setConfirmAbort(group)}
                                aria-label="Stop and discard"
                              >
                                <IconPlayerStop size={16} />
                              </ActionIcon>
                            </Tooltip>
                          </>
                        )}
                        {group.status === "paused" && (
                          <>
                            <Tooltip label="Resume from checkpoints">
                              <ActionIcon
                                variant="subtle"
                                color="green"
                                size="sm"
                                disabled={resumeMutation.isPending}
                                onClick={() => resumeMutation.mutate(group)}
                                aria-label="Resume"
                              >
                                <IconPlayerPlay size={16} />
                              </ActionIcon>
                            </Tooltip>
                            <Tooltip label="Stop and discard this tier set">
                              <ActionIcon
                                variant="subtle"
                                color="red"
                                size="sm"
                                disabled={abortMutation.isPending}
                                onClick={() => setConfirmAbort(group)}
                                aria-label="Stop and discard"
                              >
                                <IconPlayerStop size={16} />
                              </ActionIcon>
                            </Tooltip>
                          </>
                        )}
                        <Tooltip
                          label={
                            group.status === "running" || group.status === "pausing"
                              ? "Stop and discard before deleting"
                              : "Delete tier set"
                          }
                        >
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            size="sm"
                            disabled={
                              group.status === "running" ||
                              group.status === "pausing" ||
                              group.status === "pending" ||
                              deleteMutation.isPending
                            }
                            onClick={() => setConfirmDelete(group)}
                            aria-label="Delete set"
                          >
                            <IconTrash size={16} />
                          </ActionIcon>
                        </Tooltip>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        ) : (
          <Text c="dimmed">No benchmark runs yet. Select a model and tier above to get started.</Text>
        )}
      </Card>

      {suites.data && suites.data.length > 0 && (
        <Card withBorder shadow="sm">
          <Title order={4} mb="sm">Available Suites</Title>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                <Table.Th>Category</Table.Th>
                <Table.Th>Runner</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {suites.data.map((s) => (
                <Table.Tr key={s.id}>
                  <Table.Td><Text size="sm" fw={500}>{s.name}</Text></Table.Td>
                  <Table.Td>
                    <Badge variant="light">{s.category}</Badge>
                  </Table.Td>
                  <Table.Td><Text size="xs" c="dimmed">{s.runner_class}</Text></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      {(logGroup || logSolo) && (
        <BenchmarkRunLogModal
          runId={
            logGroup?.current?.id ??
            logGroup?.members.find(
              (m) => m.status === "running" || m.status === "pausing",
            )?.id ??
            logGroup?.members[0]?.id ??
            logSolo!.id
          }
          runGroupId={logGroup?.run_group_id ?? undefined}
          groupMembers={logGroup?.members}
          modelName={
            modelMap[(logGroup ?? { model_id: logSolo!.model_id }).model_id] ??
            `#${(logGroup ?? { model_id: logSolo!.model_id }).model_id}`
          }
          modelColor={
            modelMaps.byId[(logGroup ?? { model_id: logSolo!.model_id }).model_id]?.color
          }
          suiteName={
            logGroup
              ? `${tierLabel(logGroup.tier)} tier`
              : suiteMap[logSolo!.suite_id] ?? `#${logSolo!.suite_id}`
          }
          status={logGroup?.status ?? logSolo!.status}
          results={
            logGroup
              ? logGroup.members.flatMap((m) => m.results ?? [])
              : logSolo!.results ?? []
          }
          opened
          onClose={() => {
            setLogGroupId(null);
            setLogSoloRunId(null);
          }}
          onFinished={() => {
            queryClient.invalidateQueries({ queryKey: ["runs"] });
            queryClient.invalidateQueries({ queryKey: ["batch-status"] });
          }}
          onCancel={() => {
            if (logGroup) setConfirmAbort(logGroup);
            else if (logSolo) {
              setConfirmAbort({
                key: `solo-${logSolo.id}`,
                run_group_id: logSolo.run_group_id ?? null,
                model_id: logSolo.model_id,
                tier: logSolo.tier ?? null,
                status: logSolo.status,
                started_at: logSolo.started_at,
                completed_at: logSolo.completed_at,
                members: [logSolo],
                current: logSolo,
              });
            }
          }}
          onPause={() => {
            if (logGroup) pauseMutation.mutate(logGroup);
            else if (logSolo) pauseMutation.mutate({
              key: `solo-${logSolo.id}`,
              run_group_id: logSolo.run_group_id ?? null,
              model_id: logSolo.model_id,
              tier: logSolo.tier ?? null,
              status: logSolo.status,
              started_at: logSolo.started_at,
              completed_at: logSolo.completed_at,
              members: [logSolo],
              current: logSolo,
            });
          }}
          onResume={() => {
            if (logGroup) resumeMutation.mutate(logGroup);
            else if (logSolo) resumeMutation.mutate({
              key: `solo-${logSolo.id}`,
              run_group_id: logSolo.run_group_id ?? null,
              model_id: logSolo.model_id,
              tier: logSolo.tier ?? null,
              status: logSolo.status,
              started_at: logSolo.started_at,
              completed_at: logSolo.completed_at,
              members: [logSolo],
              current: logSolo,
            });
          }}
          cancelling={abortMutation.isPending}
          pausing={pauseMutation.isPending}
          resuming={resumeMutation.isPending}
        />
      )}

      {inspectRun && (
        <InspectSessionModal
          runId={inspectRun.id}
          modelName={modelMap[inspectRun.model_id] ?? `#${inspectRun.model_id}`}
          modelColor={modelMaps.byId[inspectRun.model_id]?.color}
          displayLabel={inspectRun.display_label}
          runStatus={inspectRun.status}
          opened
          onClose={() => setInspectRunId(null)}
        />
      )}

      <ConfirmDangerDialog
        opened={confirmAbort != null}
        title="Stop and discard?"
        body="This cancels the tier set and deletes all progress for it. Pause keeps checkpoints instead."
        confirmLabel="Stop and discard"
        loading={abortMutation.isPending}
        onCancel={() => setConfirmAbort(null)}
        onConfirm={() => {
          if (confirmAbort) abortMutation.mutate(confirmAbort);
        }}
      />

      <ConfirmDangerDialog
        opened={confirmDelete != null}
        title="Delete this tier set?"
        body="Removes the run group and its results from history. This cannot be undone."
        confirmLabel="Delete"
        loading={deleteMutation.isPending}
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => {
          if (confirmDelete) deleteMutation.mutate(confirmDelete);
        }}
      />
    </Stack>
  );
}
