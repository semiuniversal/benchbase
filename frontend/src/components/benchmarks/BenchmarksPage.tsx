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
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconListCheck, IconPlayerStop, IconRefresh, IconTerminal, IconTrash } from "@tabler/icons-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type RunRecord } from "../../api/client";
import { BenchmarkRunLogModal } from "./BenchmarkRunLogModal";
import { RunTimingLine } from "./RunTimingLine";
import { formatScore, shortTaskLabel, sortRunResults } from "./formatScore";
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
    case "failed": return "red";
    case "cancelled": return "orange";
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
  if (members.some((m) => m.status === "running")) return "running";
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
      members.find((m) => m.status === "running") ??
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

function axisScores(group: RunGroupRow, suiteMap: Record<number, string>) {
  const scores: { label: string; score: string; full: string }[] = [];
  for (const m of group.members) {
    const suite = suiteMap[m.suite_id] ?? `suite ${m.suite_id}`;
    const results = sortRunResults(m.results ?? []);
    if (results.length === 0) {
      scores.push({
        label: shortTaskLabel(suite, []),
        score: m.status === "completed" ? "—" : m.status.slice(0, 3),
        full: `${suite}: ${m.status}`,
      });
      continue;
    }
    for (const r of results) {
      const label = shortTaskLabel(r.task_name, results);
      const score = formatScore(r.task_name, r.score);
      const ci =
        r.ci_low != null && r.ci_high != null
          ? ` CI [${r.ci_low.toFixed(1)}, ${r.ci_high.toFixed(1)}]`
          : "";
      const n = r.n_items != null ? ` n=${r.n_items}` : "";
      scores.push({
        label,
        score,
        full: `${r.task_name}: ${score}${ci}${n} (${m.status})`,
      });
    }
  }
  return scores;
}

export function BenchmarksPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  const suites = useQuery({ queryKey: ["suites"], queryFn: api.benchmarks.suites });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.benchmarks.runs,
    refetchInterval: 5000,
  });

  const batchStatus = useQuery({
    queryKey: ["batch-status"],
    queryFn: api.benchmarks.batchStatus,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data?.status === "running") return 2000;
      if ((data?.pending_count ?? 0) > 0) return 2000;
      return false;
    },
  });

  const queueActive =
    batchStatus.data?.status === "running" ||
    (batchStatus.data?.pending_count ?? 0) > 0;
  const batchRunning = batchStatus.data?.status === "running";

  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [selectedTier, setSelectedTier] = useState<"smoke" | "standard" | "thorough">("smoke");
  const [smokeOverride, setSmokeOverride] = useState(false);
  const [logGroupId, setLogGroupId] = useState<string | null>(null);
  const [logSoloRunId, setLogSoloRunId] = useState<number | null>(null);

  const smokeSuiteIds = useMemo(() => {
    const ids = new Set<number>();
    for (const s of suites.data ?? []) {
      if (s.axis === "smoke") ids.add(s.id);
    }
    return ids;
  }, [suites.data]);

  const smokePassed = modelHasPassingSmoke(runs.data, selectedModel, smokeSuiteIds);
  const higherTiersUnlocked = smokePassed || smokeOverride;

  useEffect(() => {
    if (!higherTiersUnlocked && selectedTier !== "smoke") {
      setSelectedTier("smoke");
    }
  }, [higherTiersUnlocked, selectedTier]);

  useEffect(() => {
    setSmokeOverride(false);
  }, [selectedModel]);

  const runGroups = useMemo(
    () => groupRuns(runs.data ?? EMPTY_RUNS),
    [runs.data],
  );

  // Open live feed once when arriving via ?monitor=1 (banner Monitor button).
  const monitorParam = searchParams.get("monitor");
  useEffect(() => {
    if (monitorParam !== "1") return;
    if (batchStatus.isLoading || runs.isLoading) return;
    const gid =
      batchStatus.data?.run_group_id ??
      batchStatus.data?.current_runs?.[0]?.run_group_id ??
      runGroups.find((g) => g.status === "running")?.run_group_id ??
      null;
    const solo =
      batchStatus.data?.current_run_id ??
      runGroups.find((g) => g.status === "running")?.current?.id ??
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

  const batchMutation = useMutation({
    mutationFn: () => {
      if (!selectedModel) throw new Error("Select a model first");
      return api.benchmarks.batchStart(Number(selectedModel), selectedTier, smokeOverride);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batch-status"] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      const modelName = models.data?.find((m) => String(m.id) === selectedModel)?.name;
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

  const activeModels = models.data?.filter((m) => m.is_active || m.status === "active") ?? [];
  const modelOptions = activeModels.map((m) => ({
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
    ? runGroups.find((g) => g.run_group_id === logGroupId)
    : null;
  const logSolo = logSoloRunId != null
    ? runs.data?.find((r) => r.id === logSoloRunId)
    : null;
  const batch = batchStatus.data;
  const batchProgress =
    batch?.total != null && batch.total > 0
      ? Math.round(((batch.completed ?? 0) / batch.total) * 100)
      : 0;
  const batchLiveRunId = batchRunning ? batch?.current_run_id : null;
  const showRunningBanner =
    (queueActive || runGroups.some((g) => g.status === "running")) &&
    logGroupId === null &&
    logSoloRunId === null;

  const openMonitor = (group: RunGroupRow) => {
    if (group.run_group_id) setLogGroupId(group.run_group_id);
    else if (group.current) setLogSoloRunId(group.current.id);
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
        <Card withBorder padding="sm" bg="var(--mantine-color-blue-light)">
          <Stack gap="sm">
            {queueActive && (
              <>
                <Group justify="space-between">
                  <Text size="sm" fw={500}>
                    {batchRunning
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
                  <Progress value={batchProgress} size="sm" animated={batchRunning} />
                )}
                {batchLiveRunId != null && (
                  <RunTimingLine runId={batchLiveRunId} active={batchRunning} />
                )}
              </>
            )}
            <Group justify="flex-end">
              {batch?.run_group_id && (
                <Button
                  size="xs"
                  variant="light"
                  color="red"
                  leftSection={<IconPlayerStop size={14} />}
                  loading={abortMutation.isPending}
                  onClick={() => {
                    const g = runGroups.find((x) => x.run_group_id === batch.run_group_id);
                    if (g) abortMutation.mutate(g);
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

      <Card withBorder shadow="sm">
        <Stack>
          <Title order={4}>Launch a Tier Run</Title>
          <Text size="sm" c="dimmed">
            The tier is the only launchable unit. Smoke (1–2 min) → Standard (5–10 min) → Thorough
            (20–30 min). Standard and Thorough unlock after a passing Smoke for the selected model.
          </Text>

          {activeModels.length === 0 ? (
            <Text c="dimmed">
              No active models. Go to Settings to discover and health-check models first.
            </Text>
          ) : (
            <>
              <Select
                label="Model"
                placeholder="Select an active model"
                data={modelOptions}
                value={selectedModel}
                onChange={setSelectedModel}
                searchable
                renderOption={({ option }) => (
                  <ModelTag
                    name={option.label}
                    color={modelColor(modelMaps, { id: Number(option.value) })}
                    size="sm"
                  />
                )}
              />
              {!smokePassed && selectedModel && (
                <Checkbox
                  label="Override Smoke gate (unlocks Standard/Thorough; flagged in results)"
                  checked={smokeOverride}
                  onChange={(e) => setSmokeOverride(e.currentTarget.checked)}
                />
              )}
              <Select
                label="Tier"
                description={
                  !selectedModel
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
                  disabled={!selectedModel}
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

      <Card withBorder shadow="sm">
        <Title order={4} mb="sm">Runs</Title>
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
                      <Text size="sm" fw={500}>{tierLabel(group.tier)}</Text>
                      <Text size="xs" c="dimmed">
                        {group.members.filter((m) => m.status === "completed").length}/
                        {group.members.length} axes
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
                        {(group.status === "running" || group.status === "pending") && (
                          <Tooltip label="Stop and discard this tier set">
                            <ActionIcon
                              variant="subtle"
                              color="red"
                              size="sm"
                              disabled={abortMutation.isPending}
                              onClick={() => abortMutation.mutate(group)}
                              aria-label="Stop and discard"
                            >
                              <IconPlayerStop size={16} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                        <Tooltip
                          label={
                            group.status === "running"
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
                              group.status === "pending" ||
                              deleteMutation.isPending
                            }
                            onClick={() => deleteMutation.mutate(group)}
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
            logGroup?.members.find((m) => m.status === "running")?.id ??
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
            if (logGroup) abortMutation.mutate(logGroup);
            else if (logSolo) abortMutation.mutate({
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
        />
      )}
    </Stack>
  );
}
