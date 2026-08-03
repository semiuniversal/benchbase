import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Card,
  Group,
  Loader,
  MultiSelect,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconTrophy } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { api, type ScorecardEntry } from "../../api/client";
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

const COMPARE_SELECTION_KEY = "benchbase.compare.selectedModels";

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

function overallLabel(entry: ScorecardEntry): string {
  if (entry.overall_rank == null && entry.borda_score <= 0) {
    return "no overall score";
  }
  const ordinal =
    entry.overall_rank === 1
      ? "1st"
      : entry.overall_rank === 2
        ? "2nd"
        : entry.overall_rank === 3
          ? "3rd"
          : entry.overall_rank != null
            ? `${entry.overall_rank}th`
            : "--";
  const tie = entry.overall_rank_tied ? " tie" : "";
  const pts = entry.borda_score > 0 ? `${entry.borda_score} pts` : "0 pts";
  return `${ordinal}${tie} · ${pts}`;
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

function DimensionCell({
  dim,
  entry,
}: {
  dim: string;
  entry: ScorecardEntry;
}) {
  const d = entry.dimensions[dim];
  if (!d) {
    return <Text c="dimmed" size="sm">--</Text>;
  }
  const detailEntries =
    dim === "speed"
      ? speedDetails(d.details || {})
      : Object.entries(d.details || {}).slice(0, 4);
  const sampleCount = d.sample_count ?? 0;
  return (
    <Stack gap={2}>
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
        <Stack gap={2} mt={2}>
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
    </Stack>
  );
}

function loadSavedSelection(available: string[]): string[] | null {
  try {
    const raw = localStorage.getItem(COMPARE_SELECTION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return null;
    const names = parsed.filter((x): x is string => typeof x === "string");
    const filtered = names.filter((n) => available.includes(n));
    return filtered.length > 0 ? filtered : null;
  } catch {
    return null;
  }
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

  const availableNames = useMemo(
    () => entries.map((e) => e.model_name),
    [entries],
  );

  const [selected, setSelected] = useState<string[]>([]);
  const [selectionReady, setSelectionReady] = useState(false);

  useEffect(() => {
    if (entries.length === 0) return;
    const saved = loadSavedSelection(availableNames);
    setSelected(saved ?? availableNames);
    setSelectionReady(true);
  }, [entries, availableNames]);

  useEffect(() => {
    if (!selectionReady) return;
    localStorage.setItem(COMPARE_SELECTION_KEY, JSON.stringify(selected));
  }, [selected, selectionReady]);

  const selectedEntries = useMemo(() => {
    const set = new Set(selected);
    return entries.filter((e) => set.has(e.model_name));
  }, [entries, selected]);

  const selectData = useMemo(
    () =>
      entries.map((entry) => ({
        value: entry.model_name,
        label: `${entry.model_name} — ${overallLabel(entry)}`,
      })),
    [entries],
  );

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
        <>
          <MultiSelect
            label="Models to compare"
            description="Pick any set of models. Options show overall rank and Borda points."
            placeholder="Select models"
            data={selectData}
            value={selected}
            onChange={setSelected}
            searchable
            clearable
            hidePickedOptions
            maxDropdownHeight={320}
            renderOption={({ option }) => {
              const entry = entries.find((e) => e.model_name === option.value);
              if (!entry) return <Text size="sm">{option.label}</Text>;
              return (
                <Group gap="sm" justify="space-between" wrap="nowrap" w="100%">
                  <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
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
                  <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                    {overallLabel(entry)}
                  </Text>
                </Group>
              );
            }}
          />

          <Group gap="xs">
            <Text
              size="sm"
              c="blue"
              style={{ cursor: "pointer" }}
              onClick={() => setSelected(availableNames)}
            >
              Select all
            </Text>
            <Text size="sm" c="dimmed">·</Text>
            <Text
              size="sm"
              c="blue"
              style={{ cursor: "pointer" }}
              onClick={() => setSelected([])}
            >
              Clear
            </Text>
            <Text size="sm" c="dimmed">·</Text>
            <Text
              size="sm"
              c="blue"
              style={{ cursor: "pointer" }}
              onClick={() =>
                setSelected(
                  entries
                    .filter((e) => e.overall_rank != null && e.overall_rank <= 5)
                    .map((e) => e.model_name),
                )
              }
            >
              Top 5 overall
            </Text>
          </Group>

          {selectedEntries.length === 0 ? (
            <Text c="dimmed">Select at least one model to compare.</Text>
          ) : (
            <Card withBorder shadow="sm" padding="md">
              <Title order={4} mb="sm">
                Scorecard ({selectedEntries.length} model
                {selectedEntries.length === 1 ? "" : "s"})
              </Title>
              <Table.ScrollContainer minWidth={720}>
                <Table striped highlightOnHover withTableBorder>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th style={{ minWidth: 180 }}>Model</Table.Th>
                      <Table.Th>Overall</Table.Th>
                      {DIMENSION_ORDER.map((dim) => (
                        <Table.Th key={dim}>
                          {DIMENSION_LABELS[dim] ?? dim}
                        </Table.Th>
                      ))}
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {selectedEntries.map((entry) => (
                      <Table.Tr key={entry.model_name}>
                        <Table.Td>
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
                        </Table.Td>
                        <Table.Td>
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
                        {DIMENSION_ORDER.map((dim) => (
                          <Table.Td key={dim} style={{ verticalAlign: "top" }}>
                            <DimensionCell dim={dim} entry={entry} />
                          </Table.Td>
                        ))}
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            </Card>
          )}
        </>
      )}
    </Stack>
  );
}
