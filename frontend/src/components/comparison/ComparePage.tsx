import {
  Badge,
  Card,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconTrophy } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import {
  asModelColor,
  ModelHeading,
} from "../models/ModelColor";

const DIMENSION_LABELS: Record<string, string> = {
  speed: "Speed (effective visible tok/s)",
  coding: "Coding",
  tool_use: "Tool Use",
  reasoning: "Reasoning",
};

const DIMENSION_ORDER = ["speed", "coding", "tool_use", "reasoning"];

function rankBadge(
  rank: number | null,
  tied = false,
  competitors?: number,
) {
  if (rank === null) return <Text c="dimmed" size="sm">--</Text>;
  const color = rank === 1 ? "yellow" : rank === 2 ? "gray" : rank === 3 ? "orange" : "blue";
  const ordinal = rank === 1 ? "1st" : rank === 2 ? "2nd" : rank === 3 ? "3rd" : `${rank}th`;
  const tieLabel = tied ? " tie" : "";
  const ofLabel =
    competitors != null && competitors > 0 ? ` of ${competitors}` : "";
  return (
    <Badge
      variant="light"
      color={color}
      size="sm"
      leftSection={rank === 1 && !tied ? <IconTrophy size={12} /> : undefined}
    >
      {`${ordinal}${tieLabel}${ofLabel}`}
    </Badge>
  );
}

function formatScore(value: number | null, unit: string) {
  if (value === null) return "--";
  if (unit === "ms") return `${Math.round(value)} ms`;
  return `${value.toFixed(1)} ${unit}`;
}

const SPEED_DETAIL_LABELS: Record<string, string> = {
  output_tg: "Effective visible tok/s",
  output_ttft: "Time to first visible token",
  think_time: "Think time before visible output",
  output_token_count: "Visible output tokens",
  output_completion: "Time to last visible token",
  pp: "Prefill tok/s",
  ctx_pp: "Context prefill tok/s",
};

function formatSpeedDetail(key: string, value: number | string): string {
  if (key.includes("output_tg") || (key.includes("speed:tg") && !key.includes("think"))) {
    return `Effective visible tok/s: ${typeof value === "number" ? value.toFixed(1) : String(value)}`;
  }
  if (key.includes("think_time")) {
    return `Think time: ${typeof value === "number" ? Math.round(value) : String(value)} ms`;
  }
  if (key.includes("output_token_count")) {
    return `Visible tokens: ${typeof value === "number" ? Math.round(value) : String(value)}`;
  }
  for (const [prefix, label] of Object.entries(SPEED_DETAIL_LABELS)) {
    if (key.includes(prefix)) {
      const suffix = key.includes("ttft") || key.includes("clock") || key.includes("completion")
        ? " ms"
        : "";
      return `${label}: ${typeof value === "number" ? (suffix ? Math.round(value) : value.toFixed(1)) : String(value)}${suffix}`;
    }
  }
  const shortKey = key.split(":").pop() ?? key;
  return `${shortKey}: ${typeof value === "number" ? value.toFixed(1) : String(value)}`;
}

function speedDetails(details: Record<string, number | string>) {
  const priority = ["output_tg", "speed:tg", "output_ttft", "think_time", "output_token_count", "output_completion", "pp", "ctx_pp"];
  const entries = Object.entries(details);
  entries.sort((a, b) => {
    const rank = (key: string) => {
      const idx = priority.findIndex((p) => key.includes(p));
      return idx === -1 ? priority.length : idx;
    };
    return rank(a[0]) - rank(b[0]);
  });
  return entries.slice(0, 6);
}

export function ComparePage() {
  const scorecard = useQuery({
    queryKey: ["model-scorecard"],
    queryFn: api.results.modelScorecard,
  });

  const entries = scorecard.data ?? [];
  const hasBenchmarkHistory = entries.some((e) => e.has_benchmark_history);
  const offlineWithHistory = entries.filter(
    (e) => !e.is_active && e.has_benchmark_history,
  ).length;

  return (
    <Stack>
      <Title order={2}>Model Comparison</Title>
      <Text c="dimmed">
        Models ranked head-to-head on each benchmark dimension, including offline models
        with past benchmark runs. Speed ranks effective visible tok/s: visible tokens
        divided by total wall time to the last visible token (thinking time included,
        thinking tokens excluded). Time to first visible token and think duration are
        shown separately. Model quality (reasoning, coding, etc.) is scored separately.
      </Text>

      {scorecard.isLoading && <Loader />}

      {!scorecard.isLoading && !hasBenchmarkHistory && (
        <Text c="dimmed">
          No completed benchmark runs yet. Run benchmarks from the Benchmarks page to populate
          this scorecard.
        </Text>
      )}

      {hasBenchmarkHistory && offlineWithHistory > 0 && (
        <Text size="sm" c="dimmed">
          {offlineWithHistory} offline model{offlineWithHistory === 1 ? "" : "s"} included
          from historical runs.
        </Text>
      )}

      {hasBenchmarkHistory && entries.length > 0 && (
        <Card withBorder shadow="sm" padding="md">
          <Title order={4} mb="sm">Scorecard</Title>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Dimension</Table.Th>
                {entries.map((entry) => (
                  <Table.Th key={entry.model_name}>
                    <Group gap="xs" wrap="nowrap">
                      <ModelHeading
                        name={entry.model_name}
                        color={asModelColor(entry.model_color)}
                        size="sm"
                      />
                      {!entry.is_active && (
                        <Badge size="xs" color="gray" variant="light">
                          Offline
                        </Badge>
                      )}
                    </Group>
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              <Table.Tr style={{ fontWeight: 700 }}>
                <Table.Td>Overall</Table.Td>
                {entries.map((entry) => (
                  <Table.Td key={entry.model_name}>
                    <Group gap="xs">
                      {rankBadge(
                        entry.overall_rank,
                        entry.overall_rank_tied,
                        entry.overall_competitors,
                      )}
                      <Text size="sm" c="dimmed">
                        {entry.borda_score > 0
                          ? `${entry.borda_score} pts`
                          : "no data"}
                      </Text>
                    </Group>
                  </Table.Td>
                ))}
              </Table.Tr>

              {DIMENSION_ORDER.map((dim) => (
                <Table.Tr key={dim}>
                  <Table.Td>{DIMENSION_LABELS[dim] ?? dim}</Table.Td>
                  {entries.map((entry) => {
                    const d = entry.dimensions[dim];
                    if (!d) {
                      return <Table.Td key={entry.model_name}>--</Table.Td>;
                    }
                    const detailEntries =
                      dim === "speed"
                        ? speedDetails(d.details || {})
                        : Object.entries(d.details || {}).slice(0, 4);
                    const sampleCount = d.sample_count ?? 0;
                    return (
                      <Table.Td key={entry.model_name}>
                        <Group gap="xs" wrap="nowrap">
                          {rankBadge(d.rank, d.rank_tied, d.competitors)}
                          <Text size="sm">{formatScore(d.primary, d.unit)}</Text>
                        </Group>
                        {sampleCount > 1 && (
                          <Text size="xs" c="dimmed">avg of {sampleCount} runs</Text>
                        )}
                        {sampleCount === 1 && (
                          <Text size="xs" c="dimmed">1 run</Text>
                        )}
                        {detailEntries.length > 0 && (
                          <Stack gap={2} mt={4}>
                            {detailEntries.map(([key, val]) => (
                              <Tooltip key={key} label={key}>
                                <Text size="xs" c="dimmed">
                                  {dim === "speed"
                                    ? formatSpeedDetail(key, val)
                                    : `${key.split(":").pop()}: ${
                                        typeof val === "number" ? val.toFixed(1) : String(val)
                                      }`}
                                </Text>
                              </Tooltip>
                            ))}
                          </Stack>
                        )}
                      </Table.Td>
                    );
                  })}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </Stack>
  );
}
