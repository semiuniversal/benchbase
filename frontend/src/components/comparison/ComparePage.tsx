import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Card,
  Group,
  Loader,
  MultiSelect,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { RadarChart } from "@mantine/charts";
import { IconTrophy } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { api, type ScorecardEntry } from "../../api/client";
import { asModelColor, ModelHeading } from "../models/ModelColor";
import { SpeedPlate } from "./SpeedPlate";

export const QUALITY_AXES = [
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "tool_calling",
  "instruction",
  "structured",
  "long_context",
] as const;

const AXIS_LABELS: Record<string, string> = {
  knowledge: "Knowledge",
  reasoning: "Reasoning",
  math: "Math",
  coding: "Coding",
  tool_calling: "Tool calling",
  instruction: "Instruction",
  structured: "Structured",
  long_context: "Long context",
};

const DASH_PATTERNS = ["0", "6 3", "2 2", "8 3 2 3", "1 3", "10 2"];
const COMPARE_SELECTION_KEY = "benchbase.compare.selectedModels";

function rankBadge(rank: number | null, tied = false, competitors?: number) {
  if (rank === null) return <Text c="dimmed" size="sm">—</Text>;
  const color = rank === 1 ? "yellow" : rank === 2 ? "gray" : rank === 3 ? "orange" : "blue";
  const ordinal =
    rank === 1 ? "1st" : rank === 2 ? "2nd" : rank === 3 ? "3rd" : `${rank}th`;
  return (
    <Badge
      variant="light"
      color={color}
      size="sm"
      leftSection={rank === 1 && !tied ? <IconTrophy size={12} /> : undefined}
    >
      {`${ordinal}${tied ? " tie" : ""}${competitors ? ` of ${competitors}` : ""}`}
    </Badge>
  );
}

function formatAxisCell(d: ScorecardEntry["dimensions"][string] | undefined) {
  if (!d || d.primary == null) return { score: "—", ci: null as string | null };
  const ci =
    d.ci_low != null && d.ci_high != null
      ? `± ${Math.max(0, Math.round((d.ci_high - d.ci_low) / 2))}`
      : d.n_items != null && d.n_items < 5
        ? "n too small"
        : null;
  return { score: d.primary.toFixed(1), ci };
}

function overallLabel(entry: ScorecardEntry): string {
  if (entry.overall_rank == null && entry.borda_score <= 0) return "no overall score";
  const ordinal =
    entry.overall_rank === 1
      ? "1st"
      : entry.overall_rank === 2
        ? "2nd"
        : entry.overall_rank === 3
          ? "3rd"
          : entry.overall_rank != null
            ? `${entry.overall_rank}th`
            : "—";
  return `${ordinal}${entry.overall_rank_tied ? " tie" : ""} · ${entry.borda_score} pts`;
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

function mantineColorToken(color: string | null | undefined, index: number): string {
  const c = asModelColor(color) || "blue";
  return `${c}.${4 + (index % 4)}`;
}

export function ComparePage() {
  const scorecard = useQuery({
    queryKey: ["model-scorecard"],
    queryFn: api.results.modelScorecard,
  });

  const entries = scorecard.data ?? [];
  const hasHistory = entries.some((e) => e.has_benchmark_history);
  const availableNames = useMemo(() => entries.map((e) => e.model_name), [entries]);

  const [selected, setSelected] = useState<string[]>([]);
  const [selectionReady, setSelectionReady] = useState(false);
  const [mode, setMode] = useState<"table" | "radar">("table");
  const [stretch, setStretch] = useState(false);
  const [showBands, setShowBands] = useState(false);
  const [groupByFamily, setGroupByFamily] = useState(false);

  useEffect(() => {
    if (entries.length === 0) return;
    const saved = loadSavedSelection(availableNames);
    setSelected(saved ?? availableNames.slice(0, 6));
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

  const radarModels = useMemo(() => {
    if (groupByFamily) {
      // One representative per base_model (highest quant_rank).
      const byBase = new Map<string, ScorecardEntry>();
      for (const e of selectedEntries) {
        const key = e.base_model || e.model_name;
        const prev = byBase.get(key);
        if (!prev || (e.quant_rank ?? 0) > (prev.quant_rank ?? 0)) {
          byBase.set(key, e);
        }
      }
      return [...byBase.values()].slice(0, 6);
    }
    return selectedEntries.slice(0, 6);
  }, [selectedEntries, groupByFamily]);

  const radarData = useMemo(() => {
    const mins: Record<string, number> = {};
    const maxs: Record<string, number> = {};
    if (stretch) {
      for (const axis of QUALITY_AXES) {
        const vals = radarModels
          .map((e) => e.dimensions[axis]?.primary)
          .filter((v): v is number => v != null);
        mins[axis] = vals.length ? Math.min(...vals) : 0;
        maxs[axis] = vals.length ? Math.max(...vals) : 100;
        if (mins[axis] === maxs[axis]) {
          mins[axis] = Math.max(0, mins[axis] - 1);
          maxs[axis] = Math.min(100, maxs[axis] + 1);
        }
      }
    }

    return QUALITY_AXES.map((axis) => {
      const row: Record<string, string | number | null> = {
        axis: stretch
          ? `${AXIS_LABELS[axis]} (${mins[axis]?.toFixed(0)}–${maxs[axis]?.toFixed(0)})`
          : AXIS_LABELS[axis],
      };
      radarModels.forEach((entry) => {
        const raw = entry.dimensions[axis]?.primary;
        if (raw == null) {
          row[entry.model_name] = null;
          return;
        }
        if (!stretch) {
          row[entry.model_name] = raw;
          return;
        }
        const span = maxs[axis] - mins[axis] || 1;
        row[entry.model_name] = ((raw - mins[axis]) / span) * 100;
      });
      return row;
    });
  }, [radarModels, stretch]);

  const series = radarModels.map((entry, i) => ({
    name: entry.model_name,
    color: mantineColorToken(entry.model_color, i),
    strokeDasharray: DASH_PATTERNS[i % DASH_PATTERNS.length],
    opacity: 0.15,
  }));

  const selectData = entries.map((entry) => ({
    value: entry.model_name,
    label: `${entry.model_name} — ${overallLabel(entry)}`,
  }));

  const bandsAllowed = radarModels.length <= 3;

  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>Model Comparison</Title>
          <Text c="dimmed">
            Eight quality axes with Wilson CIs. Speed is shown as a plate — never on the radar.
            Borda overall ranks quality axes only.
          </Text>
        </div>
        <SegmentedControl
          value={mode}
          onChange={(v) => setMode(v as "table" | "radar")}
          data={[
            { label: "Table", value: "table" },
            { label: "Radar", value: "radar" },
          ]}
        />
      </Group>

      {scorecard.isLoading && <Loader />}
      {!scorecard.isLoading && !hasHistory && (
        <Text c="dimmed">No completed v2 runs yet. Launch a Smoke or Standard tier from Benchmarks.</Text>
      )}

      {hasHistory && (
        <>
          <MultiSelect
            label="Models to compare"
            description="Options show overall rank and Borda points."
            data={selectData}
            value={selected}
            onChange={setSelected}
            searchable
            clearable
            maxDropdownHeight={320}
          />
          <Group gap="md">
            <Text size="sm" c="blue" style={{ cursor: "pointer" }} onClick={() => setSelected(availableNames)}>
              Select all
            </Text>
            <Text size="sm" c="blue" style={{ cursor: "pointer" }} onClick={() => setSelected([])}>
              Clear
            </Text>
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
            {mode === "radar" && (
              <>
                <Switch
                  label={stretch ? "Stretched — differences amplified" : "Absolute 0–100"}
                  checked={stretch}
                  onChange={(e) => setStretch(e.currentTarget.checked)}
                />
                <Switch
                  label="CI bands"
                  checked={showBands && bandsAllowed}
                  disabled={!bandsAllowed}
                  onChange={(e) => setShowBands(e.currentTarget.checked)}
                />
                <Switch
                  label="Group by family"
                  checked={groupByFamily}
                  onChange={(e) => setGroupByFamily(e.currentTarget.checked)}
                />
              </>
            )}
          </Group>

          {selectedEntries.length === 0 ? (
            <Text c="dimmed">Select at least one model.</Text>
          ) : mode === "table" ? (
            <Card withBorder shadow="sm" padding="md">
              <Table.ScrollContainer minWidth={1100}>
                <Table striped highlightOnHover withTableBorder>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Model</Table.Th>
                      <Table.Th>Overall</Table.Th>
                      {QUALITY_AXES.map((a) => (
                        <Table.Th key={a}>{AXIS_LABELS[a]}</Table.Th>
                      ))}
                      <Table.Th>Speed</Table.Th>
                      <Table.Th>TTFT</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {selectedEntries.map((entry) => (
                      <Table.Tr key={entry.model_name}>
                        <Table.Td>
                          <Group gap="xs">
                            <ModelHeading
                              name={entry.model_name}
                              color={asModelColor(entry.model_color)}
                              size="sm"
                            />
                            {entry.status && entry.status !== "active" && (
                              <Badge size="xs" color="gray" variant="light">
                                {entry.status}
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
                              {entry.borda_score > 0 ? `${entry.borda_score} pts` : "no data"}
                            </Text>
                          </Group>
                        </Table.Td>
                        {QUALITY_AXES.map((axis) => {
                          const d = entry.dimensions[axis];
                          const { score, ci } = formatAxisCell(d);
                          return (
                            <Table.Td key={axis}>
                              <Group gap={4} wrap="nowrap">
                                {rankBadge(d?.rank ?? null, d?.rank_tied, d?.competitors)}
                                <Text size="sm">{score}</Text>
                              </Group>
                              {ci && (
                                <Text size="xs" c="dimmed">
                                  {ci.startsWith("±") ? `${score} ${ci}` : ci}
                                </Text>
                              )}
                              {d?.sample_count ? (
                                <Text size="xs" c="dimmed">
                                  {d.sample_count} run{d.sample_count === 1 ? "" : "s"}
                                </Text>
                              ) : null}
                            </Table.Td>
                          );
                        })}
                        <Table.Td>
                          <SpeedPlate speed={entry.speed} />
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">
                            {entry.speed?.ttft_ms != null
                              ? `${Math.round(entry.speed.ttft_ms)} ms`
                              : "—"}
                          </Text>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            </Card>
          ) : (
            <Card withBorder shadow="sm" padding="md">
              <Title order={4} mb="sm">
                Radar ({radarModels.length} model{radarModels.length === 1 ? "" : "s"}
                {stretch ? " · stretched" : ""})
              </Title>
              <RadarChart
                h={420}
                data={radarData}
                dataKey="axis"
                withPolarRadiusAxis
                withLegend
                withTooltip
                series={series.map((s) => ({
                  name: s.name,
                  color: s.color,
                  opacity: showBands && bandsAllowed ? 0.25 : 0.12,
                }))}
                radarChartProps={{ cx: "50%", cy: "50%" }}
                radarProps={(s) => {
                  const idx = series.findIndex((x) => x.name === s.name);
                  return {
                    strokeDasharray: series[idx]?.strokeDasharray,
                    connectNulls: false,
                    isAnimationActive: false,
                  };
                }}
              />
              <Group mt="md" gap="lg" align="flex-start">
                {radarModels.map((entry) => {
                  const partial = QUALITY_AXES.some(
                    (a) => entry.dimensions[a]?.primary == null,
                  );
                  return (
                    <Stack key={entry.model_name} gap={4} style={{ minWidth: 140 }}>
                      <Group gap="xs">
                        <ModelHeading
                          name={entry.model_name}
                          color={asModelColor(entry.model_color)}
                          size="sm"
                        />
                        {partial && (
                          <Tooltip label="Missing one or more axes — radar shows gaps">
                            <Badge size="xs" color="yellow" variant="light">
                              partial
                            </Badge>
                          </Tooltip>
                        )}
                      </Group>
                      <SpeedPlate speed={entry.speed} />
                    </Stack>
                  );
                })}
              </Group>
            </Card>
          )}
        </>
      )}
    </Stack>
  );
}
