import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  Progress,
  Select,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconListCheck, IconPlayerPlay, IconPlayerStop, IconRefresh, IconTerminal, IconTrash } from "@tabler/icons-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type RunRecord } from "../../api/client";
import { BenchmarkRunLogModal } from "./BenchmarkRunLogModal";
import { RunTimingLine } from "./RunTimingLine";
import { formatScore, shortTaskLabel } from "./formatScore";
import {
  buildModelMaps,
  modelColor,
  ModelTag,
} from "../models/ModelColor";

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

export function BenchmarksPage() {
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  const suites = useQuery({ queryKey: ["suites"], queryFn: api.benchmarks.suites });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.benchmarks.runs,
    refetchInterval: 5000,
  });

  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });

  const batchStatus = useQuery({
    queryKey: ["batch-status"],
    queryFn: api.benchmarks.batchStatus,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 2000 : false,
  });

  const batchRunning = batchStatus.data?.status === "running";

  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [selectedSuite, setSelectedSuite] = useState<string | null>(null);
  const [fullBenchmark, setFullBenchmark] = useState(false);
  const [logRunId, setLogRunId] = useState<number | null>(null);

  const evalModeForEstimate = fullBenchmark ? "full" : "routine";
  const suiteEstimate = useQuery({
    queryKey: ["suite-estimate", selectedSuite, evalModeForEstimate],
    queryFn: () =>
      api.benchmarks.estimate(Number(selectedSuite!), evalModeForEstimate),
    enabled: Boolean(selectedSuite),
  });

  const launchMutation = useMutation({
    mutationFn: async () => {
      if (!selectedModel || !selectedSuite) return;
      const evalMode = fullBenchmark ? "full" : "routine";
      const run = await api.benchmarks.createRun(
        Number(selectedModel),
        Number(selectedSuite),
        evalMode,
      );
      await api.benchmarks.startRun(run.id);
      return run;
    },
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      if (run) setLogRunId(run.id);
      notifications.show({
        title: "Benchmark started",
        message: "The benchmark run has been launched.",
        color: "green",
      });
    },
    onError: (err: Error) => {
      notifications.show({
        title: "Launch failed",
        message: err.message,
        color: "red",
        autoClose: 10000,
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: api.benchmarks.deleteRun,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      notifications.show({ title: "Deleted", message: "Run removed.", color: "green" });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Delete failed", message: err.message, color: "red" });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: api.benchmarks.cancelRun,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["batch-status"] });
      notifications.show({ title: "Run stopped", message: "Benchmark cancelled.", color: "orange" });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Could not stop run", message: err.message, color: "red" });
    },
  });

  const batchMutation = useMutation({
    mutationFn: api.benchmarks.batchStart,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batch-status"] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      notifications.show({
        title: "Full benchmark battery started",
        message: "Running all suites for each active model.",
        color: "green",
      });
    },
    onError: (err: Error) => {
      notifications.show({
        title: "Could not start batch",
        message: err.message,
        color: "red",
        autoClose: 10000,
      });
    },
  });

  const activeModels = models.data?.filter((m) => m.is_active) ?? [];
  const modelOptions = activeModels.map((m) => ({
    value: String(m.id),
    label: m.name,
  }));
  const suiteOptions = suites.data?.map((s) => ({
    value: String(s.id),
    label: `${s.name} (${s.category})`,
  })) ?? [];

  const modelMap = Object.fromEntries(
    (models.data ?? []).map((m) => [m.id, m.name])
  );
  const modelMaps = buildModelMaps(models.data ?? []);
  const suiteMap = Object.fromEntries(
    (suites.data ?? []).map((s) => [s.id, s.name])
  );

  const batchLimit = settings.data?.batch_sample_limit ?? 10;
  const routineLimit = settings.data?.routine_sample_limit ?? 50;

  if (models.isLoading || suites.isLoading) return <Loader />;

  const logRun = logRunId != null ? runs.data?.find((r) => r.id === logRunId) : null;
  const runningCount = runs.data?.filter((r) => r.status === "running").length ?? 0;
  const batch = batchStatus.data;
  const batchProgress =
    batch?.total != null && batch.total > 0
      ? Math.round(((batch.completed ?? 0) / batch.total) * 100)
      : 0;
  const batchLiveRunId = batchRunning ? batch?.current_run_id : null;
  const batchLabelParts = batch?.current_label?.split(" · ");
  const showRunningBanner =
    (batchRunning || runningCount > 0) && logRunId === null;

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
            {batchRunning && (
              <>
                <Group justify="space-between">
                  <Text size="sm" fw={500}>
                    Running full battery — {batch?.completed ?? 0}/{batch?.total ?? 0}
                    {batch?.failed ? ` (${batch.failed} failed)` : ""}
                  </Text>
                  {batch?.current_label && (
                    <Text size="xs" c="dimmed">{batch.current_label}</Text>
                  )}
                </Group>
                <Progress value={batchProgress} size="sm" animated />
                {batch?.estimate_label && (
                  <Text size="xs" c="dimmed">
                    Est. full battery: {batch.estimate_label}
                    {batch.per_model_label ? ` (${batch.per_model_label} per model)` : ""}
                  </Text>
                )}
                {batchLiveRunId != null && (
                  <RunTimingLine runId={batchLiveRunId} active={batchRunning} />
                )}
              </>
            )}
            {!batchRunning && runningCount > 0 && (
              <Text size="sm">
                {runningCount} benchmark{runningCount > 1 ? "s" : ""} running
              </Text>
            )}
            <Group justify="flex-end">
              {batchRunning && batchLiveRunId != null && (
                <Button
                  size="xs"
                  variant="light"
                  color="red"
                  leftSection={<IconPlayerStop size={14} />}
                  loading={cancelMutation.isPending}
                  onClick={() => cancelMutation.mutate(batchLiveRunId)}
                >
                  Stop current run
                </Button>
              )}
              <Button
                size="xs"
                variant="light"
                leftSection={<IconTerminal size={14} />}
                onClick={() => {
                  if (batchLiveRunId != null) {
                    setLogRunId(batchLiveRunId);
                    return;
                  }
                  const active = runs.data?.find((r) => r.status === "running");
                  if (active) setLogRunId(active.id);
                }}
                disabled={!batchLiveRunId && runningCount === 0}
              >
                View live output
              </Button>
            </Group>
          </Stack>
        </Card>
      )}

      <Card withBorder shadow="sm">
        <Stack>
          <Title order={4}>Launch a Benchmark</Title>

          {activeModels.length === 0 ? (
            <Text c="dimmed">
              No active models. Go to Settings to discover and health-check models first.
            </Text>
          ) : (
            <>
              <Group grow>
                <Select
                  label="Model"
                  placeholder="Select a model"
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
                <Select
                  label="Benchmark Suite"
                  placeholder="Select a suite"
                  data={suiteOptions}
                  value={selectedSuite}
                  onChange={setSelectedSuite}
                />
              </Group>
              <Checkbox
                label="Full benchmark (entire datasets, no sample cap)"
                checked={fullBenchmark}
                onChange={(e) => setFullBenchmark(e.currentTarget.checked)}
              />
              {fullBenchmark && (
                <Alert
                  color="red"
                  variant="light"
                  icon={<IconAlertTriangle size={18} />}
                  title="This can take hours — or days on a slow model"
                >
                  Full benchmarks run complete datasets. Reasoning alone can be well over 10,000
                  questions (GSM8K, ARC-Easy, HellaSwag, MMLU). HumanEval runs all 164 problems.
                  Only use this when you need publication-grade numbers and can leave the machine
                  running overnight or longer.
                </Alert>
              )}
              {!fullBenchmark && (
                <Text size="xs" c="dimmed">
                  Routine run uses {routineLimit} samples per task from Settings (speed: 5
                  iterations). Scores are indicative, not full-suite metrics.
                  {suiteEstimate.data?.estimate_label
                    ? ` Rough time: ${suiteEstimate.data.estimate_label}.`
                    : ""}
                </Text>
              )}
              {fullBenchmark && suiteEstimate.data?.estimate_label && (
                <Text size="xs" c="dimmed">
                  Rough time estimate: {suiteEstimate.data.estimate_label}.
                </Text>
              )}
              <Group>
                <Button
                  leftSection={<IconPlayerPlay size={16} />}
                  disabled={!selectedModel || !selectedSuite || batchRunning}
                  loading={launchMutation.isPending}
                  onClick={() => launchMutation.mutate()}
                >
                  Run Benchmark
                </Button>
                <Button
                  variant="light"
                  leftSection={<IconListCheck size={16} />}
                  disabled={batchRunning || !suites.data?.length}
                  loading={batchMutation.isPending}
                  onClick={() => batchMutation.mutate()}
                >
                  Run All Benchmarks
                </Button>
              </Group>
              <Text size="xs" c="dimmed">
                Run All uses {batchLimit} samples per task from Settings (speed: 3 iterations).
                Quick comparison across all suites — not full metrics.
              </Text>
            </>
          )}
        </Stack>
      </Card>

      <Card withBorder shadow="sm">
        <Title order={4} mb="sm">Runs</Title>
        {runs.isLoading ? (
          <Loader />
        ) : runs.data && runs.data.length > 0 ? (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>ID</Table.Th>
                <Table.Th>Model</Table.Th>
                <Table.Th>Suite</Table.Th>
                <Table.Th>Results</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Started</Table.Th>
                <Table.Th>Completed</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {runs.data.map((run: RunRecord) => (
                <Table.Tr key={run.id}>
                  <Table.Td>{run.id}</Table.Td>
                  <Table.Td>
                    <ModelTag
                      name={modelMap[run.model_id] ?? `#${run.model_id}`}
                      color={modelColor(modelMaps, { id: run.model_id })}
                    />
                  </Table.Td>
                  <Table.Td>{suiteMap[run.suite_id] ?? `#${run.suite_id}`}</Table.Td>
                  <Table.Td>
                    {run.results && run.results.length > 0 ? (
                      <Stack gap={2}>
                        {run.results.slice(0, 3).map((r) => (
                          <Text key={r.task_name} size="sm">
                            <Text span c="dimmed" size="xs">{shortTaskLabel(r.task_name)}: </Text>
                            <Text span fw={700}>{formatScore(r.task_name, r.score)}</Text>
                          </Text>
                        ))}
                        {run.results.length > 3 && (
                          <Text size="xs" c="dimmed">+{run.results.length - 3} more</Text>
                        )}
                      </Stack>
                    ) : (
                      <Text size="xs" c="dimmed">—</Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Badge color={statusColor(run.status)} variant="light">
                      {run.status}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs">
                      {run.started_at
                        ? new Date(run.started_at).toLocaleString()
                        : "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs">
                      {run.completed_at
                        ? new Date(run.completed_at).toLocaleString()
                        : "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <Tooltip label="View output">
                        <ActionIcon
                          variant="subtle"
                          size="sm"
                          onClick={() => setLogRunId(run.id)}
                          aria-label="View run log"
                        >
                          <IconTerminal size={16} />
                        </ActionIcon>
                      </Tooltip>
                      {run.status === "running" && (
                        <Tooltip label="Stop run">
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            size="sm"
                            disabled={cancelMutation.isPending}
                            onClick={() => cancelMutation.mutate(run.id)}
                            aria-label="Stop run"
                          >
                            <IconPlayerStop size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      <Tooltip
                      label={
                        run.status === "running"
                          ? "Stop the run before deleting"
                          : "Delete run"
                      }
                    >
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        size="sm"
                        disabled={run.status === "running" || deleteMutation.isPending}
                        onClick={() => deleteMutation.mutate(run.id)}
                        aria-label="Delete run"
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Tooltip>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <Text c="dimmed">No benchmark runs yet. Select a model and suite above to get started.</Text>
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

      {logRunId != null && (
        <BenchmarkRunLogModal
          runId={logRunId}
          modelName={
            logRun
              ? modelMap[logRun.model_id] ?? `#${logRun.model_id}`
              : batchLiveRunId === logRunId && batchLabelParts?.[0]
                ? batchLabelParts[0]
                : `#${logRunId}`
          }
          modelColor={
            logRun
              ? modelMaps.byId[logRun.model_id]?.color
              : batchLiveRunId === logRunId && batchLabelParts?.[0]
                ? modelMaps.byName[batchLabelParts[0]]?.color
                : undefined
          }
          suiteName={
            logRun
              ? suiteMap[logRun.suite_id] ?? `#${logRun.suite_id}`
              : batchLiveRunId === logRunId && batchLabelParts?.[1]
                ? batchLabelParts[1]
                : "—"
          }
          status={logRun?.status ?? "running"}
          results={logRun?.results ?? []}
          opened={logRunId !== null}
          onClose={() => setLogRunId(null)}
          onFinished={() => {
            queryClient.invalidateQueries({ queryKey: ["runs"] });
            queryClient.invalidateQueries({ queryKey: ["batch-status"] });
          }}
          onCancel={() => cancelMutation.mutate(logRunId)}
          cancelling={cancelMutation.isPending}
        />
      )}
    </Stack>
  );
}
