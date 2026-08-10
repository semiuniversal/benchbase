import {
  Badge,
  Button,
  Card,
  Code,
  Grid,
  Group,
  Modal,
  ScrollArea,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconPlayerStop } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";
import { api, type RunRecord, type RunResultSummary } from "../../api/client";
import { asModelColor, ModelTag } from "../models/ModelColor";
import { formatScore, shortTaskLabel, sortRunResults } from "./formatScore";
import { RunTimingLine } from "./RunTimingLine";

interface LogLine {
  stream: string;
  text: string;
}

interface BenchmarkRunLogModalProps {
  runId: number;
  runGroupId?: string | null;
  groupMembers?: RunRecord[];
  modelName: string;
  modelColor?: string;
  suiteName: string;
  status: string;
  results: RunResultSummary[];
  opened: boolean;
  onClose: () => void;
  onFinished?: () => void;
  onCancel?: () => void;
  cancelling?: boolean;
}

function lineColor(stream: string) {
  // Log panel is always dark-8; do not use theme-dependent tokens like
  // --mantine-color-dimmed (nearly invisible in light mode).
  switch (stream) {
    case "stderr":
      return "var(--mantine-color-red-4)";
    case "system":
      return "var(--mantine-color-gray-5)";
    default:
      return "var(--mantine-color-gray-2)";
  }
}

export function BenchmarkRunLogModal({
  runId,
  runGroupId,
  groupMembers,
  modelName,
  modelColor,
  suiteName,
  status,
  results,
  opened,
  onClose,
  onFinished,
  onCancel,
  cancelling = false,
}: BenchmarkRunLogModalProps) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [liveStatus, setLiveStatus] = useState(status);
  const [activeRunId, setActiveRunId] = useState(runId);
  const [loadingLog, setLoadingLog] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const seenRuns = useRef<Set<number>>(new Set());

  useEffect(() => {
    setLiveStatus(status);
  }, [status]);

  const memberKey = (groupMembers ?? [])
    .map((m) => `${m.id}:${m.status}`)
    .join(",");

  useEffect(() => {
    if (!opened) return;

    setLines([]);
    setLoadingLog(true);
    seenRuns.current = new Set();
    let cancelled = false;
    let es: EventSource | null = null;

    const appendSystem = (text: string) => {
      setLines((prev) => [...prev, { stream: "system", text }]);
    };

    const attachToRun = async (id: number, label?: string) => {
      if (seenRuns.current.has(id) && es) return;
      es?.close();
      setActiveRunId(id);
      if (label) appendSystem(`\n--- ${label} (run #${id}) ---\n`);

      try {
        const data = await api.benchmarks.logHistory(id);
        if (!cancelled && data.lines.length > 0) {
          setLines((prev) => {
            const existing = new Set(prev.map((l) => `${l.stream}|${l.text}`));
            const fresh = data.lines.filter(
              (l) => !existing.has(`${l.stream}|${l.text}`),
            );
            return fresh.length ? [...prev, ...fresh] : prev;
          });
        }
      } catch {
        // history optional
      } finally {
        setLoadingLog(false);
      }

      const member = groupMembers?.find((m) => m.id === id);
      const memberStatus = member?.status ?? status;
      if (memberStatus !== "running" && memberStatus !== "pending") {
        seenRuns.current.add(id);
        return;
      }

      es = new EventSource(`/api/benchmarks/runs/${id}/log`);
      es.addEventListener("log", (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as LogLine;
          setLines((prev) => [...prev, data]);
        } catch {
          // skip
        }
      });
      es.addEventListener("done", async (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as { status?: string };
          if (data.status) setLiveStatus(data.status);
        } catch {
          // ignore
        }
        es?.close();
        es = null;
        seenRuns.current.add(id);
        onFinished?.();

        if (!runGroupId) return;
        const refreshed = await api.benchmarks.runs().catch(() => null);
        const siblings =
          refreshed?.filter((r) => r.run_group_id === runGroupId).sort((a, b) => a.id - b.id) ??
          groupMembers ??
          [];
        const next =
          siblings.find((m) => m.status === "running") ??
          siblings.find((m) => m.status === "pending" && !seenRuns.current.has(m.id));
        if (next && !cancelled) {
          await attachToRun(next.id, `Axis run #${next.id}`);
          return;
        }
        const allDone = siblings.every((m) =>
          ["completed", "failed", "cancelled"].includes(m.status),
        );
        if (allDone) {
          setLiveStatus(
            siblings.some((m) => m.status === "failed")
              ? "failed"
              : siblings.some((m) => m.status === "cancelled")
                ? "cancelled"
                : "completed",
          );
        }
      });
      es.onerror = () => es?.close();
    };

    (async () => {
      if (runGroupId && groupMembers?.length) {
        const ordered = [...groupMembers].sort((a, b) => a.id - b.id);
        for (const m of ordered) {
          if (m.status === "completed" || m.status === "failed") {
            appendSystem(`\n--- completed axis run #${m.id} ---\n`);
            try {
              const hist = await api.benchmarks.logHistory(m.id);
              if (!cancelled && hist.lines.length) {
                setLines((prev) => [...prev, ...hist.lines]);
              }
            } catch {
              // ignore
            }
            seenRuns.current.add(m.id);
          }
        }
        const live =
          ordered.find((m) => m.status === "running") ??
          ordered.find((m) => m.status === "pending") ??
          ordered[ordered.length - 1];
        if (live && !cancelled) {
          await attachToRun(live.id, `Live · run #${live.id}`);
        } else {
          setLoadingLog(false);
        }
      } else {
        await attachToRun(runId);
      }
    })();

    return () => {
      cancelled = true;
      es?.close();
    };
    // memberKey tracks status changes without re-binding every render identity
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, runId, runGroupId, memberKey]);

  useEffect(() => {
    if (!opened) return;
    const active = liveStatus === "running" || liveStatus === "pending";
    if (!active) return;
    const poll = window.setInterval(() => {
      api.benchmarks
        .logHistory(activeRunId)
        .then((data) => {
          if (data.lines.length > 0) {
            setLines((prev) => (data.lines.length > prev.length ? data.lines : prev));
          }
        })
        .catch(() => {});
    }, 3000);
    return () => window.clearInterval(poll);
  }, [opened, activeRunId, liveStatus]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines]);

  const displayStatus = liveStatus;
  const doneAxes =
    groupMembers?.filter((m) => m.status === "completed").length ?? null;
  const totalAxes = groupMembers?.length ?? null;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xl"
      title={
        <Group gap="sm">
          <Text fw={600}>{runGroupId ? "Tier set" : `Run #${runId}`}</Text>
          <ModelTag name={modelName} color={asModelColor(modelColor)} size="sm" />
          <Text size="sm" c="dimmed">
            · {suiteName}
            {doneAxes != null && totalAxes != null ? ` (${doneAxes}/${totalAxes})` : ""}
          </Text>
          <Badge
            size="sm"
            variant="light"
            color={
              displayStatus === "completed"
                ? "green"
                : displayStatus === "failed"
                  ? "red"
                  : displayStatus === "cancelled"
                    ? "orange"
                    : "blue"
            }
          >
            {displayStatus}
          </Badge>
        </Group>
      }
    >
      <Stack>
        {(displayStatus === "running" || displayStatus === "pending") && (
          <Group justify="space-between">
            <RunTimingLine runId={activeRunId} active />
            {onCancel && (
              <Button
                size="xs"
                color="red"
                variant="light"
                leftSection={<IconPlayerStop size={14} />}
                loading={cancelling}
                onClick={onCancel}
              >
                Stop and discard
              </Button>
            )}
          </Group>
        )}

        {results.length > 0 && (
          <Card withBorder padding="sm">
            <Title order={5} mb="xs">Scores</Title>
            <Grid>
              {sortRunResults(results).map((r) => (
                <Grid.Col span={6} key={r.task_name}>
                  <Text size="sm">
                    <Text span c="dimmed" size="xs">
                      {shortTaskLabel(r.task_name, results)}:{" "}
                    </Text>
                    <Text span fw={700}>
                      {formatScore(r.task_name, r.score)}
                    </Text>
                  </Text>
                </Grid.Col>
              ))}
            </Grid>
          </Card>
        )}

        <ScrollArea h={360} viewportRef={scrollRef}>
          <Code
            block
            style={{
              whiteSpace: "pre-wrap",
              fontSize: 12,
              minHeight: 340,
              background: "var(--mantine-color-dark-8)",
              color: "var(--mantine-color-gray-2)",
            }}
          >
            {loadingLog && lines.length === 0
              ? "Loading log…"
              : lines.length === 0
                ? "Waiting for output…"
                : lines.map((l, i) => (
                    <span key={i} style={{ color: lineColor(l.stream) }}>
                      {l.text.endsWith("\n") ? l.text : `${l.text}\n`}
                    </span>
                  ))}
          </Code>
        </ScrollArea>
      </Stack>
    </Modal>
  );
}
