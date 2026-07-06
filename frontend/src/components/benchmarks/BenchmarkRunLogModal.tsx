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
import { api, type RunResultSummary } from "../../api/client";
import { asModelColor, ModelTag } from "../models/ModelColor";
import { formatScore, shortTaskLabel } from "./formatScore";
import { RunTimingLine } from "./RunTimingLine";

interface LogLine {
  stream: string;
  text: string;
}

interface BenchmarkRunLogModalProps {
  runId: number;
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
  switch (stream) {
    case "stderr":
      return "var(--mantine-color-red-4)";
    case "system":
      return "var(--mantine-color-dimmed)";
    default:
      return undefined;
  }
}

export function BenchmarkRunLogModal({
  runId,
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
  const [loadingLog, setLoadingLog] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!opened) return;

    setLines([]);
    setLiveStatus(status);
    setLoadingLog(true);

    let es: EventSource | null = null;

    api.benchmarks.logHistory(runId)
      .then((data) => {
        if (data.lines.length > 0) {
          setLines(data.lines);
        }
      })
      .catch(() => {
        // history optional
      })
      .finally(() => setLoadingLog(false));

    if (status === "running" || status === "pending") {
      es = new EventSource(`/api/benchmarks/runs/${runId}/log`);

      es.addEventListener("log", (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as LogLine;
          setLines((prev) => [...prev, data]);
        } catch {
          // skip malformed
        }
      });

      es.addEventListener("done", (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as { status?: string };
          if (data.status) setLiveStatus(data.status);
        } catch {
          // ignore
        }
        es?.close();
        onFinished?.();
      });

      es.onerror = () => es?.close();
    }

    return () => es?.close();
  }, [opened, runId, status, onFinished]);

  useEffect(() => {
    if (!opened) return;
    const active = liveStatus === "running" || liveStatus === "pending";
    if (!active) return;

    const poll = window.setInterval(() => {
      api.benchmarks.logHistory(runId)
        .then((data) => {
          if (data.lines.length > 0) {
            setLines((prev) => (data.lines.length > prev.length ? data.lines : prev));
          }
        })
        .catch(() => {
          // backup while tools emit \\r progress without newlines
        });
    }, 3000);

    return () => window.clearInterval(poll);
  }, [opened, runId, liveStatus]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines]);

  const displayStatus = liveStatus;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <Group gap="sm">
          <Text fw={600}>Run #{runId}</Text>
          <ModelTag name={modelName} color={asModelColor(modelColor)} size="sm" />
          <Text size="sm" c="dimmed">· {suiteName}</Text>
          <Badge
            size="sm"
            variant="light"
            color={
              displayStatus === "completed"
                ? "green"
                : displayStatus === "failed"
                  ? "red"
                  : displayStatus === "running"
                    ? "blue"
                    : displayStatus === "cancelled"
                      ? "orange"
                      : "gray"
            }
          >
            {displayStatus}
          </Badge>
        </Group>
      }
      size="xl"
      styles={{ body: { paddingTop: 0 } }}
    >
      <Stack gap="md">
        {displayStatus === "running" && (
          <RunTimingLine runId={runId} active={opened} />
        )}
        {displayStatus === "running" && onCancel && (
          <Group justify="flex-end">
            <Button
              size="xs"
              variant="light"
              color="red"
              leftSection={<IconPlayerStop size={14} />}
              loading={cancelling}
              onClick={onCancel}
            >
              Stop run
            </Button>
          </Group>
        )}

        {results.length > 0 && (
          <Card withBorder padding="md" bg="var(--mantine-color-default-hover)">
            <Title order={5} mb="sm">Results</Title>
            <Grid>
              {results.map((r) => (
                <Grid.Col key={r.task_name} span={{ base: 12, sm: 6 }}>
                  <Stack gap={2}>
                    <Text size="xs" c="dimmed">{shortTaskLabel(r.task_name)}</Text>
                    <Text size="xl" fw={700}>{formatScore(r.task_name, r.score)}</Text>
                  </Stack>
                </Grid.Col>
              ))}
            </Grid>
          </Card>
        )}

        {displayStatus === "failed" && results.length === 0 && (
          <Text c="red" size="sm">This run failed. Check the log below for errors.</Text>
        )}

        <Text size="sm" fw={600}>Console output</Text>
        <ScrollArea h={480} offsetScrollbars viewportRef={scrollRef}>
          <Code
            block
            style={{
              whiteSpace: "pre-wrap",
              fontSize: "0.8rem",
              lineHeight: 1.45,
              minHeight: 300,
              padding: "0.75rem",
            }}
          >
            {lines.length === 0 ? (
              <Text c="dimmed" size="sm">
                {loadingLog || displayStatus === "running"
                  ? "Loading output…"
                  : "No console log saved for this run."}
              </Text>
            ) : (
              lines.map((line, i) => (
                <span key={i} style={{ color: lineColor(line.stream) }}>
                  {line.text}
                </span>
              ))
            )}
          </Code>
        </ScrollArea>
      </Stack>
    </Modal>
  );
}
