import { Badge, Button, Group, Modal, Stack, Table, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconRefresh } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type RunRecord } from "../../api/client";
import { formatScore, sortRunResults } from "./formatScore";
import type { RunGroupRow } from "./runGroupTypes";

function tierLabel(tier: string | null | undefined) {
  if (tier === "smoke") return "Smoke";
  if (tier === "thorough") return "Thorough";
  if (tier === "standard") return "Standard";
  return tier ?? "Run";
}

function memberScoreText(m: RunRecord): string {
  const results = sortRunResults(m.results ?? []);
  if (results.length === 0) {
    if (m.status === "completed") return "—";
    return m.status;
  }
  if (results.length === 1) {
    return formatScore(results[0].task_name, results[0].score);
  }
  return results
    .map((r) => `${formatScore(r.task_name, r.score)}`)
    .join(" · ");
}

export function canRerunMember(m: RunRecord, group: RunGroupRow): boolean {
  if (
    m.status === "running" ||
    m.status === "pending" ||
    m.status === "pausing" ||
    m.status === "paused"
  ) {
    return false;
  }
  if (
    group.status === "running" ||
    group.status === "pending" ||
    group.status === "pausing" ||
    group.status === "paused"
  ) {
    return false;
  }
  return true;
}

export function canOpenRerunDialog(group: RunGroupRow): boolean {
  if (
    group.status === "running" ||
    group.status === "pending" ||
    group.status === "pausing"
  ) {
    return false;
  }
  return group.members.some((m) => canRerunMember(m, group));
}

type Props = {
  group: RunGroupRow | null;
  suiteMap: Record<number, string>;
  modelName: string;
  onClose: () => void;
};

export function RerunBenchmarkModal({ group, suiteMap, modelName, onClose }: Props) {
  const queryClient = useQueryClient();
  const [busyRunId, setBusyRunId] = useState<number | null>(null);
  const [rerunAllBusy, setRerunAllBusy] = useState(false);

  const opened = group != null;

  const afterRerun = () => {
    void queryClient.invalidateQueries({ queryKey: ["runs"] });
    void queryClient.invalidateQueries({ queryKey: ["batch-status"] });
  };

  const singleRerun = useMutation({
    mutationFn: (runId: number) => api.benchmarks.rerunRun(runId),
    onMutate: (runId) => setBusyRunId(runId),
    onSettled: () => setBusyRunId(null),
    onSuccess: () => {
      notifications.show({
        title: "Axis rerun queued",
        message: "Prior scores for that benchmark were cleared.",
        color: "blue",
      });
      afterRerun();
    },
    onError: (err: Error) => {
      notifications.show({ title: "Rerun failed", message: err.message, color: "red" });
    },
  });

  const rerunEntireSet = async () => {
    if (!group) return;
    const targets = group.members.filter((m) => canRerunMember(m, group));
    if (targets.length === 0) return;
    setRerunAllBusy(true);
    try {
      for (const m of targets) {
        await api.benchmarks.rerunRun(m.id);
      }
      notifications.show({
        title: "Tier rerun queued",
        message: `Re-running ${targets.length} benchmark${targets.length === 1 ? "" : "s"} in this set.`,
        color: "blue",
      });
      afterRerun();
      onClose();
    } catch (e) {
      notifications.show({
        title: "Rerun failed",
        message: e instanceof Error ? e.message : String(e),
        color: "red",
      });
    } finally {
      setRerunAllBusy(false);
    }
  };

  const rerunnableCount = group?.members.filter((m) => canRerunMember(m, group)).length ?? 0;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Rerun benchmark"
      size="lg"
      centered
    >
      {group && (
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            {tierLabel(group.tier)} tier · {modelName} · {group.members.length} phases.
            Reruns clear stored scores and run each benchmark again from scratch (not checkpoint
            resume).
          </Text>

          <Button
            leftSection={<IconRefresh size={16} />}
            loading={rerunAllBusy}
            disabled={rerunnableCount === 0 || singleRerun.isPending}
            onClick={() => void rerunEntireSet()}
          >
            Rerun entire tier set ({rerunnableCount}{" "}
            {rerunnableCount === 1 ? "axis" : "axes"})
          </Button>

          <Stack gap="xs">
            <Text size="sm" fw={600}>
              Phases in this set
            </Text>
            <Table striped highlightOnHover withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Benchmark</Table.Th>
                  <Table.Th>Score</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {group.members.map((m) => {
                  const suite = suiteMap[m.suite_id] ?? `Suite #${m.suite_id}`;
                  const ok = canRerunMember(m, group);
                  return (
                    <Table.Tr key={m.id}>
                      <Table.Td>
                        <Text size="sm">{suite}</Text>
                        <Text size="xs" c="dimmed">
                          Run #{m.id}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" fw={500}>
                          {memberScoreText(m)}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge size="sm" variant="light">
                          {m.status}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Group justify="flex-end">
                          <Button
                            size="compact-sm"
                            variant="light"
                            leftSection={<IconRefresh size={14} />}
                            disabled={!ok}
                            loading={busyRunId === m.id}
                            onClick={() => singleRerun.mutate(m.id)}
                          >
                            Rerun
                          </Button>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Stack>

          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Close
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}